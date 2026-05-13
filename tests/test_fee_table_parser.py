import asyncio
import json

import pytest
from pydantic import ValidationError

from agent.fee_table_parser.event_schema import RawFeeTableEvent, parse_raw_jsonl
from agent.fee_table_parser.llm_provider import LLMFeeTableEventProvider
from agent.fee_table_parser.models import (
    ColumnTerm,
    FeeCategoryInfo,
    FeeCategoryTerm,
    FeeTableParseInput,
)
from agent.fee_table_parser.parser import FeeTableLogicAreaParser
from agent.fee_table_parser.reducer import FeeTableStreamReducer
from agent.fee_table_parser.scheduler import MockFeeTableEventProvider
from agent.fee_table_parser.validation import validate_fee_category_tree
from agent.llm.config import OpenAISettings
from agent.llm.llm_client import LLMClient


def test_root_columns_are_column_terms_and_leaf_columns_are_field_id_refs():
    column = ColumnTerm(
        field_id="2026051300003001",
        column_key="amount",
        pdf_example="0.00",
        pdf_field_name="Amount",
    )
    root = FeeCategoryTerm(
        fee_category_id="fee_table_root",
        fee_category_type="parent",
        seq=0,
        fee_category_info=FeeCategoryInfo(fee_category_name="fee_table_root", is_display_name=False),
        columns=[column],
        children=[
            FeeCategoryTerm(
                fee_category_id="2026051300001001",
                fee_category_type="leaf",
                seq=1,
                fee_category_info=FeeCategoryInfo(
                    fee_category_name="Usage",
                    pdf_field_name="Usage",
                    category_type="charge",
                ),
                columns=["2026051300003001"],
            )
        ],
    )

    validate_fee_category_tree(root)
    assert root.columns[0].column_key == "amount"
    assert root.children[0].columns == ["2026051300003001"]


def test_column_logic_node_name_uses_column_key():
    column = ColumnTerm(
        field_id="2026051300003001",
        column_key="amount_2",
        pdf_example="0.00",
        pdf_field_name="Total Amount",
    )

    assert column.logic_data_node.node_name == "amount_2"
    assert column.logic_data_node.node_id == "mock_2026051300003001"


def test_leaf_requires_business_category_type_and_parent_forbids_it():
    leaf = FeeCategoryTerm(
        fee_category_id="2026051300001001",
        fee_category_type="leaf",
        seq=1,
        fee_category_info=FeeCategoryInfo(fee_category_name="Leaf"),
    )
    with pytest.raises(ValueError, match="leaf.*category_type"):
        validate_fee_category_tree(leaf)

    parent = FeeCategoryTerm(
        fee_category_id="2026051300001002",
        fee_category_type="parent",
        seq=1,
        fee_category_info=FeeCategoryInfo(fee_category_name="Parent", category_type="charge"),
    )
    with pytest.raises(ValueError, match="parent.*category_type"):
        validate_fee_category_tree(parent)


def test_parent_cannot_contain_columns_except_root():
    parent = FeeCategoryTerm(
        fee_category_id="2026051300000001",
        fee_category_type="parent",
        seq=1,
        fee_category_info=FeeCategoryInfo(fee_category_name="Parent"),
        columns=[
            ColumnTerm(
                field_id="2026051300003001",
                column_key="amount",
                pdf_example="0.00",
                pdf_field_name="Amount",
            )
        ],
    )

    with pytest.raises(ValueError, match="non-root parent.*columns"):
        validate_fee_category_tree(parent)


def test_leaf_cannot_contain_children():
    leaf = FeeCategoryTerm(
        fee_category_id="2026051300000001",
        fee_category_type="leaf",
        seq=1,
        fee_category_info=FeeCategoryInfo(fee_category_name="Leaf", category_type="charge"),
        children=[
            FeeCategoryTerm(
                fee_category_id="2026051300000002",
                fee_category_type="leaf",
                seq=1,
                fee_category_info=FeeCategoryInfo(fee_category_name="Child", category_type="charge"),
            )
        ],
    )

    with pytest.raises(ValueError, match="leaf.*children"):
        validate_fee_category_tree(leaf)


def test_leaf_columns_must_reference_root_columns():
    root = FeeCategoryTerm(
        fee_category_id="fee_table_root",
        fee_category_type="parent",
        seq=0,
        fee_category_info=FeeCategoryInfo(fee_category_name="fee_table_root", is_display_name=False),
        children=[
            FeeCategoryTerm(
                fee_category_id="2026051300001001",
                fee_category_type="leaf",
                seq=1,
                fee_category_info=FeeCategoryInfo(fee_category_name="Usage", category_type="charge"),
                columns=["missing_field"],
            )
        ],
    )

    with pytest.raises(ValueError, match="unknown root column"):
        validate_fee_category_tree(root)


def test_raw_column_detected_does_not_accept_ids():
    with pytest.raises(ValidationError):
        parse_raw_jsonl(
            json.dumps(
                {
                    "event_type": "column_detected",
                    "target_id": "llm_should_not_send_this",
                    "payload": {
                        "column_key": "amount",
                        "pdf_example": "0.00",
                        "pdf_field_name": "Amount",
                    },
                }
            )
        )

    events = parse_raw_jsonl(
        json.dumps(
            {
                "event_type": "column_detected",
                "payload": {
                    "column_key": "amount",
                    "pdf_example": "0.00",
                    "pdf_field_name": "Amount",
                },
            }
        )
    )

    assert len(events) == 1
    assert events[0].payload["column_key"] == "amount"
    assert not hasattr(events[0], "target_id")


def test_raw_category_detected_uses_path_and_rejects_corrected_status():
    event = RawFeeTableEvent.model_validate(
        {
            "event_type": "category_detected",
            "payload": {
                "path": ["Exceeding package"],
                "fee_category_name": "Exceeding package",
                "fee_category_type": "parent",
            },
        }
    )
    assert event.status == "confirmed"

    with pytest.raises(ValueError, match="Only confirmed"):
        RawFeeTableEvent.model_validate(
            {
                "event_type": "category_detected",
                "status": "corrected",
                "payload": {
                    "path": ["Exceeding package"],
                    "fee_category_name": "Exceeding package",
                    "fee_category_type": "parent",
                },
            }
        )


def test_column_key_collision_with_different_pdf_name_splits_column_key():
    reducer = FeeTableStreamReducer(id_generator=SequentialIdGenerator())
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "column_key": "amount",
                        "pdf_example": "10.00",
                        "pdf_field_name": "Amount",
                    },
                },
                {
                    "event_type": "column_detected",
                    "payload": {
                        "column_key": "amount",
                        "pdf_example": "20.00",
                        "pdf_field_name": "Total Amount",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
            ]
        )
    )

    assert [column.column_key for column in reducer.root.columns] == ["amount", "amount_2"]


def test_column_detected_after_columns_finalized_is_ignored():
    reducer = FeeTableStreamReducer(id_generator=SequentialIdGenerator())
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "column_key": "amount",
                        "pdf_example": "10.00",
                        "pdf_field_name": "Amount",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
                {
                    "event_type": "column_detected",
                    "payload": {
                        "column_key": "late",
                        "pdf_example": "ignored",
                        "pdf_field_name": "Late",
                    },
                },
            ]
        )
    )

    assert [column.column_key for column in reducer.root.columns] == ["amount"]


def test_category_path_generates_ids_and_leaf_refs_root_field_ids():
    reducer = FeeTableStreamReducer(id_generator=SequentialIdGenerator())
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "column_key": "amount",
                        "pdf_example": "10.00",
                        "pdf_field_name": "Amount",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
            ]
        )
    )
    field_id = reducer.root.columns[0].field_id
    result = reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "category_detected",
                    "payload": {
                        "path": ["Exceeding package", "INTERNATIONAL ROAMING"],
                        "fee_category_name": "INTERNATIONAL ROAMING",
                        "fee_category_type": "leaf",
                        "category_type": "charge",
                    },
                },
                {
                    "event_type": "leaf_columns_bound",
                    "payload": {
                        "path": ["Exceeding package", "INTERNATIONAL ROAMING"],
                        "field_ids": [field_id],
                    },
                },
                {
                    "event_type": "category_closed",
                    "payload": {"path": ["Exceeding package", "INTERNATIONAL ROAMING"]},
                },
            ]
        )
    )
    reducer.finalize_category_stream()

    parent = reducer.root.children[0]
    leaf = parent.children[0]
    assert parent.fee_category_info.fee_category_name == "Exceeding package"
    assert leaf.columns == [field_id]
    assert result.closed_category_ids == [leaf.fee_category_id]


def test_category_closed_can_arrive_before_detected_and_is_applied_later():
    reducer = FeeTableStreamReducer(id_generator=SequentialIdGenerator())
    result = reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "category_closed",
                    "payload": {"path": ["Usage"]},
                },
                {
                    "event_type": "category_detected",
                    "payload": {
                        "path": ["Usage"],
                        "fee_category_name": "Usage",
                        "fee_category_type": "leaf",
                        "category_type": "charge",
                    },
                },
            ]
        )
    )
    reducer.finalize_category_stream()

    assert len(result.closed_category_ids) == 1
    assert reducer.root.children[0].closed is True


def test_missing_parent_path_is_auto_created_and_output():
    reducer = FeeTableStreamReducer(id_generator=SequentialIdGenerator())
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "category_detected",
                    "payload": {
                        "path": ["A", "B"],
                        "fee_category_name": "B",
                        "fee_category_type": "leaf",
                        "category_type": "free_unit",
                    },
                },
                {
                    "event_type": "category_closed",
                    "payload": {"path": ["A", "B"]},
                },
            ]
        )
    )
    reducer.finalize_category_stream()

    parent = reducer.root.children[0]
    assert parent.fee_category_type == "parent"
    assert parent.fee_category_info.fee_category_name == "A"
    assert parent.children[0].fee_category_info.fee_category_name == "B"


def test_leaf_can_close_without_columns_bound():
    reducer = FeeTableStreamReducer(id_generator=SequentialIdGenerator())
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "category_detected",
                    "payload": {
                        "path": ["Usage"],
                        "fee_category_name": "Usage",
                        "fee_category_type": "leaf",
                        "category_type": "charge",
                    },
                },
                {"event_type": "category_closed", "payload": {"path": ["Usage"]}},
            ]
        )
    )
    reducer.finalize_category_stream()

    assert reducer.root.children[0].columns == []
    assert reducer.root.children[0].closed is True


def test_unresolved_pending_category_closed_fails_at_stream_end():
    reducer = FeeTableStreamReducer(id_generator=SequentialIdGenerator())
    reducer.consume_raw_jsonl(
        json.dumps({"event_type": "category_closed", "payload": {"path": ["Missing"]}})
    )

    with pytest.raises(ValueError, match="pending category_closed"):
        reducer.finalize_category_stream()


def test_parser_sync_wrapper_runs_async_two_call_flow():
    parser = FeeTableLogicAreaParser(event_provider=MockFeeTableEventProvider())

    logic_area = parser.parse_fee_table_logic_area(
        FeeTableParseInput(content_type="excel_md", md="mock fee table")
    )

    root = logic_area.fee_table.fee_category_tree
    root_field_ids = {column.field_id for column in root.columns}
    leaf = _find_category(root, "INTERNATIONAL ROAMING")
    assert logic_area.parse_status == "finalized"
    assert root.columns
    assert leaf.columns
    assert set(leaf.columns).issubset(root_field_ids)
    assert leaf.summary_info == []
    assert leaf.loop_info is None
    assert leaf.children_sort_rule is None


def test_async_scheduler_calls_column_before_category():
    provider = RecordingAsyncProvider()
    parser = FeeTableLogicAreaParser(event_provider=provider)

    asyncio.run(
        parser.parse_fee_table_logic_area_async(
            FeeTableParseInput(content_type="excel_md", md="mock fee table")
        )
    )

    assert provider.calls == ["root_columns", "categories"]
    assert "amount" in provider.received_column_pool_json


def test_pdf_input_image_url_enters_parser_source_view():
    parser = FeeTableLogicAreaParser(event_provider=MockFeeTableEventProvider())
    source = parser.normalize_input(
        FeeTableParseInput(content_type="pdf_image", image_url="https://example.com/table.png")
    )

    assert source.visual_input == "https://example.com/table.png"
    assert source.text_input is None


def test_excel_input_md_enters_parser_source_view():
    parser = FeeTableLogicAreaParser(event_provider=MockFeeTableEventProvider())
    source = parser.normalize_input(FeeTableParseInput(content_type="excel_md", md="| fee | amount |"))

    assert source.text_input == "| fee | amount |"
    assert source.visual_input is None


def test_parser_uses_real_llm_provider_when_settings_are_usable():
    settings = OpenAISettings(
        enabled=True,
        api_key="test-key",
        base_url="https://example.com/v1",
        base_model="text-model",
        vl_model="vision-model",
        timeout_seconds=3,
    )
    parser = FeeTableLogicAreaParser.from_settings(settings=settings)

    assert isinstance(parser.scheduler.provider, LLMFeeTableEventProvider)


def test_parser_falls_back_to_mock_provider_without_usable_llm_settings():
    settings = OpenAISettings(
        enabled=True,
        api_key="",
        base_url=None,
        base_model="text-model",
        vl_model="vision-model",
        timeout_seconds=3,
    )
    parser = FeeTableLogicAreaParser.from_settings(settings=settings)

    assert isinstance(parser.scheduler.provider, MockFeeTableEventProvider)


def test_parser_falls_back_to_mock_provider_with_blank_llm_api_key():
    settings = OpenAISettings(
        enabled=True,
        api_key="   ",
        base_url=None,
        base_model="text-model",
        vl_model="vision-model",
        timeout_seconds=3,
    )
    parser = FeeTableLogicAreaParser.from_settings(settings=settings)

    assert isinstance(parser.scheduler.provider, MockFeeTableEventProvider)


def test_llm_provider_root_columns_uses_column_prompt():
    client = RecordingLLMClient(
        response=_jsonl(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "column_key": "amount",
                        "pdf_example": "0.00",
                        "pdf_field_name": "Amount",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
            ]
        )
    )
    provider = LLMFeeTableEventProvider(client=client)

    asyncio.run(
        provider.root_columns(
            FeeTableLogicAreaParser(event_provider=MockFeeTableEventProvider()).normalize_input(
                FeeTableParseInput(content_type="excel_md", md="| fee | amount |")
            )
        )
    )

    assert "Allowed events: column_detected, columns_finalized" in client.calls[0]["prompt"]
    assert "Do not output ids" in client.calls[0]["prompt"]
    assert client.calls[0]["llm_name"] == "base"


def test_llm_provider_categories_receives_column_pool_json():
    client = RecordingLLMClient(
        response=_jsonl(
            [
                {
                    "event_type": "category_detected",
                    "payload": {
                        "path": ["Usage"],
                        "fee_category_name": "Usage",
                        "fee_category_type": "leaf",
                        "category_type": "charge",
                    },
                },
                {"event_type": "category_closed", "payload": {"path": ["Usage"]}},
            ]
        )
    )
    provider = LLMFeeTableEventProvider(client=client)

    asyncio.run(
        provider.categories(
            FeeTableLogicAreaParser(event_provider=MockFeeTableEventProvider()).normalize_input(
                FeeTableParseInput(content_type="excel_md", md="mock")
            ),
            column_pool_json='[{"field_id":"2026051300003001","column_key":"amount"}]',
        )
    )

    assert "Allowed events: category_detected, leaf_columns_bound, category_closed" in client.calls[0]["prompt"]
    assert "2026051300003001" in client.calls[0]["prompt"]
    assert "amount" in client.calls[0]["prompt"]


def test_llm_provider_calls_vision_model_for_pdf_image_jsonl_events():
    client = RecordingLLMClient(
        response=json.dumps(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "column_key": "amount",
                        "pdf_example": "0.00",
                        "pdf_field_name": "Amount",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
            ]
        )
    )
    provider = LLMFeeTableEventProvider(client=client)

    asyncio.run(
        provider.root_columns(
            FeeTableLogicAreaParser(event_provider=MockFeeTableEventProvider()).normalize_input(
                FeeTableParseInput(content_type="pdf_image", image_url="https://example.com/table.png")
            )
        )
    )

    assert client.calls[0]["llm_name"] == "vl"
    assert client.calls[0]["model"] == "vision-model"
    assert client.calls[0]["image_url"] == "https://example.com/table.png"


def test_llm_provider_rejects_disallowed_event_type_for_task():
    client = RecordingLLMClient(
        response=json.dumps(
            {
                "event_type": "category_detected",
                "payload": {
                    "path": ["Usage"],
                    "fee_category_name": "Usage",
                    "fee_category_type": "leaf",
                    "category_type": "charge",
                },
            }
        )
    )
    provider = LLMFeeTableEventProvider(client=client)

    with pytest.raises(ValueError, match="not allowed"):
        asyncio.run(
            provider.root_columns(
                FeeTableLogicAreaParser(event_provider=MockFeeTableEventProvider()).normalize_input(
                    FeeTableParseInput(content_type="excel_md", md="| fee | amount |")
                )
            )
        )


def _jsonl(events):
    return "\n".join(json.dumps(event) for event in events)


def _find_category(root, name):
    if root.fee_category_info.fee_category_name == name:
        return root
    for child in root.children:
        try:
            return _find_category(child, name)
        except LookupError:
            pass
    raise LookupError(name)


class SequentialIdGenerator:
    def __init__(self):
        self.next_value = 1

    def new_id(self):
        value = f"20260513{self.next_value:08d}"
        self.next_value += 1
        return value


class RecordingAsyncProvider:
    def __init__(self):
        self.calls = []
        self.received_column_pool_json = ""

    async def root_columns(self, source_view):
        self.calls.append("root_columns")
        return _jsonl(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "column_key": "amount",
                        "pdf_example": "0.00",
                        "pdf_field_name": "Amount",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
            ]
        )

    async def categories(self, source_view, column_pool_json):
        self.calls.append("categories")
        self.received_column_pool_json = column_pool_json
        field_id = json.loads(column_pool_json)[0]["field_id"]
        return _jsonl(
            [
                {
                    "event_type": "category_detected",
                    "payload": {
                        "path": ["Usage"],
                        "fee_category_name": "Usage",
                        "fee_category_type": "leaf",
                        "category_type": "charge",
                    },
                },
                {
                    "event_type": "leaf_columns_bound",
                    "payload": {"path": ["Usage"], "field_ids": [field_id]},
                },
                {"event_type": "category_closed", "payload": {"path": ["Usage"]}},
            ]
        )


class RecordingLLMClient(LLMClient):
    def __init__(self, response: str):
        super().__init__(
            OpenAISettings(
                enabled=True,
                api_key="test-key",
                base_url="https://example.com/v1",
                base_model="text-model",
                vl_model="vision-model",
                timeout_seconds=3,
            )
        )
        self.response = response
        self.calls = []

    def complete(self, *, prompt, model, llm_name="base", image_url=None, response_format=None):
        self.calls.append(
            {
                "prompt": prompt,
                "model": model,
                "llm_name": llm_name,
                "image_url": image_url,
                "response_format": response_format,
            }
        )
        return self.response
