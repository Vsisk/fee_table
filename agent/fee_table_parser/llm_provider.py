from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from agent.fee_table_parser.event_schema import PROMPT_ALLOWED_EVENT_TYPES, RawFeeTableEvent
from agent.fee_table_parser.models import FeeCategoryTerm, FeeTableSourceView
from agent.llm.llm_client import OpenAILLMClient
from agent.llm.types import StreamJsonlObject


class ColumnsDetectedResult:
    columns_set: set[dict[str, str]]
    columns_number: int


class CategoryDetectedResult:
    fee_table: FeeCategoryTerm


class FeeTableTaskResult:
    status: str
    result: ColumnsDetectedResult | CategoryDetectedResult


class LLMFeeTableEventProvider:
    """Network LLM-backed raw JSONL event provider for fee table parsing."""

    def __init__(self, client: OpenAILLMClient | None = None) -> None:
        self.client = client or OpenAILLMClient()

    async def root_columns(self, source_view: FeeTableSourceView) -> AsyncIterator[RawFeeTableEvent]:
        return self._run_task("root_columns", source_view)

    async def categories(
        self,
        source_view: FeeTableSourceView,
        column_pool_json: str,
    ) -> AsyncIterator[RawFeeTableEvent]:
        return self._run_task("categories", source_view, column_pool_json=column_pool_json)

    async def _run_task(
        self,
        task: str,
        source_view: FeeTableSourceView,
        **variables: str,
    ) -> AsyncIterator[RawFeeTableEvent]:
        stream = self.client.generate_result_by_llm(
            prompt_template=[_prompt_template_name(task)],
            stream=True,
            response_format=None,
            image_url=source_view.visual_input if source_view.visual_input else None,
            table_md="",
            **variables,
        )
        allowed_event_types = PROMPT_ALLOWED_EVENT_TYPES[task]

        async for item in stream:
            event = _validate_stream_item(item)
            if event.event_type not in allowed_event_types:
                raise ValueError(f"event_type {event.event_type} is not allowed for task {task}")
            yield event


def _prompt_template_name(task: str) -> str:
    return f"fee_table_{task}"


def _source_block(source_view: FeeTableSourceView) -> str:
    if source_view.content_type == "pdf_image":
        return (
            "Input type: pdf_image\n"
        )
    return (
        "Input type: excel_md\n"
        "Excel Markdown or semi-structured text:\n"
        f"{source_view.text_input or ''}"
    )


def _validate_stream_item(item: StreamJsonlObject | Any) -> RawFeeTableEvent:
    payload = item.object if isinstance(item, StreamJsonlObject) else item
    return RawFeeTableEvent.model_validate(payload)
