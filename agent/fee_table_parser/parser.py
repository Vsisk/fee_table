from __future__ import annotations

import asyncio

from agent.fee_table_parser.llm_provider import LLMFeeTableEventProvider
from agent.fee_table_parser.models import FeeTableLogicArea, FeeTableParseInput, FeeTableSourceView
from agent.fee_table_parser.reducer import FeeTableStreamReducer
from agent.fee_table_parser.scheduler import (
    FeeTableCategoryScheduler,
    FeeTableEventProvider,
    MockFeeTableEventProvider,
)
from agent.llm.config import OpenAISettings, load_openai_settings
from agent.llm.llm_client import LLMClient


class FeeTableLogicAreaParser:
    def __init__(self, event_provider: FeeTableEventProvider | None = None) -> None:
        self.scheduler = FeeTableCategoryScheduler(event_provider or _default_event_provider())

    @classmethod
    def from_settings(cls, settings: OpenAISettings) -> "FeeTableLogicAreaParser":
        if settings.is_usable:
            return cls(LLMFeeTableEventProvider(client=LLMClient(settings=settings)))
        return cls(MockFeeTableEventProvider())

    def normalize_input(self, parse_input: FeeTableParseInput) -> FeeTableSourceView:
        if parse_input.content_type == "pdf_image":
            return FeeTableSourceView(
                content_type=parse_input.content_type,
                visual_input=parse_input.image_url,
                text_input=None,
            )
        return FeeTableSourceView(
            content_type=parse_input.content_type,
            visual_input=None,
            text_input=parse_input.md,
        )

    async def parse_fee_table_logic_area_async(self, parse_input: FeeTableParseInput) -> FeeTableLogicArea:
        source_view = self.normalize_input(parse_input)
        reducer = FeeTableStreamReducer(source_view=source_view)
        await self.scheduler.run(source_view, reducer)
        return reducer.finalize_section()

    def parse_fee_table_logic_area(self, parse_input: FeeTableParseInput) -> FeeTableLogicArea:
        return asyncio.run(self.parse_fee_table_logic_area_async(parse_input))


def _default_event_provider() -> FeeTableEventProvider:
    settings = load_openai_settings()
    if settings.is_usable:
        return LLMFeeTableEventProvider(client=LLMClient(settings=settings))
    return MockFeeTableEventProvider()
