import json

from agent.fee_table_parser.reducer import FeeTableStreamReducer


def test_first_leaf_category_becomes_leaf_root_with_columns_definition():
    reducer = FeeTableStreamReducer()
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "cbs_key": "amount",
                        "pdf_exp": "10.00",
                        "pdf_key": "Amount",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
            ]
        )
    )
    field_id = json.loads(reducer.column_pool_prompt_json())[0]["field_id"]
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "category_leaf",
                    "payload": {
                        "fee_category_name": "Usage",
                        "category_type": "charge",
                        "field_ids": [field_id],
                    },
                },
            ]
        )
    )
    reducer.finalize_category_stream()

    assert reducer.root.fee_category_type == "leaf"
    assert reducer.root.fee_category_info.fee_category_name == "Usage"
    assert reducer.root.columns_definition[0].field_name == "Amount"
    assert reducer.root.columns == [field_id]


def test_first_parent_category_creates_root_with_columns_definition():
    reducer = FeeTableStreamReducer()
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "cbs_key": "amount",
                        "pdf_exp": "10.00",
                        "pdf_key": "Amount",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
                {
                    "event_type": "category_open",
                    "payload": {
                        "fee_category_name": "Usage group",
                    },
                },
                {"event_type": "category_close", "payload": {}},
            ]
        )
    )

    assert reducer.root.fee_category_type == "root"
    assert reducer.root.columns_definition[0].field_name == "Amount"
    assert reducer.root.children[0].fee_category_type == "parent"
    assert reducer.root.children[0].fee_category_info.fee_category_name == "Usage group"


def test_parent_category_must_be_explicitly_closed():
    reducer = FeeTableStreamReducer()
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {"event_type": "columns_finalized", "payload": {}},
                {
                    "event_type": "category_open",
                    "payload": {"fee_category_name": "Usage group"},
                },
            ]
        )
    )

    try:
        reducer.finalize_category_stream()
    except ValueError as exc:
        assert "category stack has unclosed parent categories" in str(exc)
    else:
        raise AssertionError("expected unclosed parent category to fail")


def test_stack_protocol_nests_leaf_under_current_parent():
    reducer = FeeTableStreamReducer()
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "cbs_key": "amount",
                        "pdf_exp": "10.00",
                        "pdf_key": "Amount",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
            ]
        )
    )
    field_id = reducer.column_pool_prompt_json()
    field_id = json.loads(field_id)[0]["field_id"]
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "category_open",
                    "payload": {"fee_category_name": "Usage group"},
                },
                {
                    "event_type": "category_leaf",
                    "payload": {
                        "fee_category_name": "Usage",
                        "category_type": "charge",
                        "field_ids": [field_id],
                    },
                },
                {"event_type": "category_close", "payload": {}},
            ]
        )
    )
    reducer.finalize_category_stream()

    parent = reducer.root.children[0]
    assert parent.fee_category_info.fee_category_name == "Usage group"
    assert parent.children[0].fee_category_info.fee_category_name == "Usage"
    assert parent.children[0].columns == [field_id]


def test_summary_detected_after_leaf_attaches_summary_info_to_leaf():
    reducer = FeeTableStreamReducer()
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "cbs_key": "amount",
                        "pdf_exp": "10.00",
                        "pdf_key": "Amount",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
            ]
        )
    )
    field_id = json.loads(reducer.column_pool_prompt_json())[0]["field_id"]

    reducer.consume_raw_jsonl(
        _jsonl(
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
    )
    reducer.finalize_category_stream()

    summary = reducer.root.summary_info[0]
    assert summary.summary_title == "Usage Total"
    assert summary.summary_fields[0].summary_type == "sum"
    assert summary.summary_fields[0].field_id == [field_id]


def test_summary_detected_accepts_grouped_field_ids_for_total_not_in_root_columns():
    reducer = FeeTableStreamReducer()
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "cbs_key": "amount",
                        "pdf_exp": "10.00",
                        "pdf_key": "Amount",
                    },
                },
                {
                    "event_type": "column_detected",
                    "payload": {
                        "cbs_key": "vat",
                        "pdf_exp": "1.00",
                        "pdf_key": "VAT",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
            ]
        )
    )
    columns = json.loads(reducer.column_pool_prompt_json())
    amount_id = next(column["field_id"] for column in columns if column["column_key"] == "amount")
    vat_id = next(column["field_id"] for column in columns if column["column_key"] == "vat")

    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "category_open",
                    "payload": {"fee_category_name": "Usage group"},
                },
                {
                    "event_type": "summary_detected",
                    "payload": {
                        "summary_title": "Grand Total",
                        "summary_type": "sum",
                        "field_id": [[amount_id, vat_id]],
                    },
                },
                {
                    "event_type": "category_leaf",
                    "payload": {
                        "fee_category_name": "Usage",
                        "category_type": "charge",
                        "field_ids": [amount_id, vat_id],
                    },
                },
                {"event_type": "category_close", "payload": {}},
            ]
        )
    )
    reducer.finalize_category_stream()
    logic_area = reducer.finalize_section()

    parent = logic_area.fee_table.fee_category_tree.children[0]
    summary_field = parent.summary_info[0].summary_fields[0]
    assert parent.summary_info[0].summary_title == "Grand Total"
    assert summary_field.field_id == [amount_id, vat_id]
    assert summary_field.summary_type == "sum"


def _jsonl(events):
    return "\n".join(json.dumps(event) for event in events)
