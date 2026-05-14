from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any, Protocol

from agent.fee_table_parser.event_schema import CATEGORY_EVENT_TYPES, COLUMN_EVENT_TYPES, RawFeeTableEvent
from agent.fee_table_parser.models import FeeTableEventType, FeeTableSourceView
from agent.fee_table_parser.reducer import FeeTableStreamReducer


class FeeTableEventProvider(Protocol):
    async def root_columns(self, source_view: FeeTableSourceView) -> str | AsyncIterator[Any]: ...

    async def categories(
        self,
        source_view: FeeTableSourceView,
        column_pool_json: str,
    ) -> str | AsyncIterator[Any]: ...


class FeeTableCategoryScheduler:
    def __init__(self, provider: FeeTableEventProvider | None = None) -> None:
        self.provider = provider or MockFeeTableEventProvider()
        self._lock = asyncio.Lock()
        self.mock_enriched_category_ids: list[str] = []

    async def run(self, source_view: FeeTableSourceView, reducer: FeeTableStreamReducer) -> None:
        column_events = await self.provider.root_columns(source_view)
        async with self._lock:
            await _consume_provider_output(reducer, column_events, COLUMN_EVENT_TYPES)
        reducer.ensure_columns_finalized()

        column_pool_json = reducer.column_pool_prompt_json()
        category_events = await self.provider.categories(source_view, column_pool_json)
        async with self._lock:
            result = await _consume_provider_output(reducer, category_events, CATEGORY_EVENT_TYPES)
            result.extend(reducer.finalize_category_stream())

        await self._trigger_mock_enrichment(result.closed_category_ids)

    async def _trigger_mock_enrichment(self, closed_category_ids: list[str]) -> None:
        self.mock_enriched_category_ids.extend(closed_category_ids)


class MockFeeTableEventProvider:
    async def root_columns(self, source_view: FeeTableSourceView) -> str:
        return _jsonl(
            [
                {
                    "event_type": "column_detected",
                    "payload": {
                        "column_key": "description",
                        "pdf_example": "Voice Call",
                        "pdf_field_name": "Description",
                    },
                },
                {
                    "event_type": "column_detected",
                    "payload": {
                        "column_key": "amount",
                        "pdf_example": "99.00",
                        "pdf_field_name": "Amount",
                    },
                },
                {
                    "event_type": "column_detected",
                    "payload": {
                        "column_key": "quantity",
                        "pdf_example": "2 SMS",
                        "pdf_field_name": "Quantity",
                    },
                },
                {"event_type": "columns_finalized", "payload": {}},
            ]
        )

    async def categories(self, source_view: FeeTableSourceView, column_pool_json: str) -> str:
        columns = json.loads(column_pool_json)
        by_key = {column["column_key"]: column["field_id"] for column in columns}
        description = by_key["description"]
        amount = by_key["amount"]
        quantity = by_key["quantity"]
        return _jsonl(
            [
                {
                    "event_type": "category_detected",
                    "payload": {
                        "path": ["Exceeding package"],
                        "fee_category_name": "Exceeding package",
                        "fee_category_type": "parent",
                    },
                },
                {
                    "event_type": "category_detected",
                    "payload": {
                        "path": ["Exceeding package", "EXCEEDING PACKAGE"],
                        "fee_category_name": "EXCEEDING PACKAGE",
                        "fee_category_type": "leaf",
                        "category_type": "charge",
                    },
                },
                {
                    "event_type": "leaf_columns_bound",
                    "payload": {
                        "path": ["Exceeding package", "EXCEEDING PACKAGE"],
                        "field_ids": [description, quantity, amount],
                    },
                },
                {
                    "event_type": "category_closed",
                    "payload": {"path": ["Exceeding package", "EXCEEDING PACKAGE"]},
                },
                {
                    "event_type": "category_detected",
                    "payload": {
                        "path": ["Exceeding package", "INTERNATIONAL CALLS"],
                        "fee_category_name": "INTERNATIONAL CALLS",
                        "fee_category_type": "leaf",
                        "category_type": "charge",
                    },
                },
                {
                    "event_type": "leaf_columns_bound",
                    "payload": {
                        "path": ["Exceeding package", "INTERNATIONAL CALLS"],
                        "field_ids": [description, amount],
                    },
                },
                {
                    "event_type": "category_closed",
                    "payload": {"path": ["Exceeding package", "INTERNATIONAL CALLS"]},
                },
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
                        "field_ids": [description, amount],
                    },
                },
                {
                    "event_type": "category_closed",
                    "payload": {"path": ["Exceeding package", "INTERNATIONAL ROAMING"]},
                },
                {
                    "event_type": "category_closed",
                    "payload": {"path": ["Exceeding package"]},
                },
            ]
        )


def _jsonl(events: list[dict]) -> str:
    return "\n".join(json.dumps(event) for event in events)


async def _consume_provider_output(
    reducer: FeeTableStreamReducer,
    output: str | AsyncIterator[Any],
    allowed_event_types: set[FeeTableEventType],
):
    if isinstance(output, str):
        return reducer.consume_raw_jsonl(output, allowed_event_types=allowed_event_types)

    result = reducer.consume_raw_jsonl("", allowed_event_types=allowed_event_types)
    async for raw_event in output:
        event = raw_event if isinstance(raw_event, RawFeeTableEvent) else RawFeeTableEvent.model_validate(raw_event)
        if event.event_type not in allowed_event_types:
            raise ValueError(f"event_type {event.event_type} is not allowed")
        result.extend(reducer.consume_raw_event(event))
    return result
