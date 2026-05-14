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
    field_id = reducer.root.columns_definition[0].field_id
    reducer.consume_raw_jsonl(
        _jsonl(
            [
                {
                    "event_type": "leaf_columns_bound",
                    "payload": {"path": ["Usage"], "field_ids": [field_id]},
                },
                {"event_type": "category_closed", "payload": {"path": ["Usage"]}},
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
                    "event_type": "category_detected",
                    "payload": {
                        "path": ["Usage group"],
                        "fee_category_name": "Usage group",
                        "fee_category_type": "parent",
                    },
                },
            ]
        )
    )

    assert reducer.root.fee_category_type == "root"
    assert reducer.root.columns_definition[0].field_name == "Amount"
    assert reducer.root.children[0].fee_category_type == "parent"
    assert reducer.root.children[0].fee_category_info.fee_category_name == "Usage group"


def _jsonl(events):
    return "\n".join(json.dumps(event) for event in events)
