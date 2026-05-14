import asyncio
import json

from agent.fee_table_parser.llm_provider import LLMFeeTableEventProvider
from agent.fee_table_parser.models import FeeTableEventType, FeeTableSourceView
from agent.fee_table_parser.reducer import FeeTableStreamReducer
from agent.fee_table_parser.scheduler import FeeTableCategoryScheduler
from agent.llm.prompt_manager import PromptManager
from agent.llm.types import StreamJsonlObject


def test_llm_provider_streams_validated_column_events():
    asyncio.run(_assert_llm_provider_streams_validated_column_events())


def test_llm_provider_streams_validated_category_summary_events():
    asyncio.run(_assert_llm_provider_streams_validated_category_summary_events())


async def _assert_llm_provider_streams_validated_column_events():
    client = FakeStreamingClient(
        [
            {
                "event_type": "column_detected",
                "payload": {
                    "cbs_key": "amount",
                    "pdf_exp": "10.00",
                    "pdf_key": "Amount",
                    "is_sum": True,
                },
            },
            {"event_type": "columns_finalized", "payload": {}},
        ]
    )
    provider = LLMFeeTableEventProvider(client=client)

    events = [
        event
        async for event in await provider.root_columns(
            FeeTableSourceView(content_type="excel_md", text_input="| Amount |\n| 10.00 |")
        )
    ]

    assert [event.event_type for event in events] == [
        FeeTableEventType.COLUMN_DETECTED,
        FeeTableEventType.COLUMNS_FINALIZED,
    ]
    assert client.calls[0]["stream"] is True
    assert client.calls[0]["prompt_template"] == ["fee_table_root_columns"]
    assert client.calls[0]["table_md"] == "| Amount |\n| 10.00 |"
    assert client.calls[0]["specific_extraction_rules"] == ""
    assert client.calls[0]["query"] == ""


async def _assert_llm_provider_streams_validated_category_summary_events():
    field_id = "amount_id"
    client = FakeStreamingClient(
        [
            {
                "event_type": "category_leaf",
                "payload": {
                    "fee_category_name": "Usage",
                    "category_type": "charge",
                    "field_ids": [field_id],
                },
            },
            {
                "event_type": "summary_detected",
                "payload": {
                    "summary_title": "Usage Total",
                    "summary_type": "sum",
                    "field_id": [field_id],
                },
            },
        ]
    )
    provider = LLMFeeTableEventProvider(client=client)

    events = [
        event
        async for event in await provider.categories(
            FeeTableSourceView(content_type="excel_md", text_input="table"),
            json.dumps([{"field_id": field_id, "column_key": "amount"}]),
        )
    ]

    assert [event.event_type for event in events] == [
        FeeTableEventType.CATEGORY_LEAF,
        FeeTableEventType.SUMMARY_DETECTED,
    ]
    assert client.calls[0]["prompt_template"] == ["fee_table_categories"]
    assert client.calls[0]["column_pool_json"] == json.dumps(
        [{"field_id": field_id, "column_key": "amount"}]
    )


def test_scheduler_consumes_provider_event_streams():
    asyncio.run(_assert_scheduler_consumes_provider_event_streams())


async def _assert_scheduler_consumes_provider_event_streams():
    source_view = FeeTableSourceView(content_type="excel_md", text_input="table")
    scheduler = FeeTableCategoryScheduler(StreamingEventProvider())
    reducer = FeeTableStreamReducer()

    await scheduler.run(source_view, reducer)

    logic_area = reducer.finalize_section()
    root = logic_area.fee_table.fee_category_tree
    assert root.fee_category_type == "leaf"
    assert root.columns == [root.columns_definition[0].field_id]


def test_default_prompt_catalog_contains_fee_table_stream_templates():
    manager = PromptManager()

    root_columns_prompt = manager.build_prompt_text(["fee_table_root_columns"])
    categories_prompt = manager.build_prompt_text(["fee_table_categories"])

    assert "column_detected" in root_columns_prompt
    assert "columns_finalized" in root_columns_prompt
    assert "specific_extraction_rules" in root_columns_prompt
    assert "table_md" in root_columns_prompt
    assert "query" in root_columns_prompt
    assert "category_open" in categories_prompt
    assert "category_leaf" in categories_prompt
    assert "category_close" in categories_prompt
    assert "summary_detected" in categories_prompt
    assert "summary_type" in categories_prompt
    assert "Do not output path" in categories_prompt


class FakeStreamingClient:
    def __init__(self, objects):
        self.objects = objects
        self.calls = []

    def generate_result_by_llm(self, **kwargs):
        self.calls.append(kwargs)
        return self._stream()

    async def _stream(self):
        for index, item in enumerate(self.objects):
            yield StreamJsonlObject(object=item, raw_line="{}", index=index)


class StreamingEventProvider:
    async def root_columns(self, source_view):
        return self._root_columns()

    async def categories(self, source_view, column_pool_json):
        columns = json.loads(column_pool_json)
        return self._categories(columns[0]["field_id"])

    async def _root_columns(self):
        yield {
            "event_type": "column_detected",
            "payload": {
                "cbs_key": "amount",
                "pdf_exp": "10.00",
                "pdf_key": "Amount",
                "is_sum": False,
            },
        }
        yield {"event_type": "columns_finalized", "payload": {}}

    async def _categories(self, field_id):
        yield {
            "event_type": "category_leaf",
            "payload": {
                "fee_category_name": "Usage",
                "category_type": "charge",
                "field_ids": [field_id],
            },
        }


class SequentialIdGenerator:
    def __init__(self):
        self.next_value = 1

    def new_id(self):
        value = f"20260513{self.next_value:08d}"
        self.next_value += 1
        return value
