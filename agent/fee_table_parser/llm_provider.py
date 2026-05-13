from __future__ import annotations

import asyncio
import json
import re

from agent.fee_table_parser.event_schema import PROMPT_ALLOWED_EVENT_TYPES, parse_raw_jsonl
from agent.fee_table_parser.models import FeeTableSourceView
from agent.fee_table_parser.prompts import PROMPTS
from agent.llm.llm_client import LLMClient


class LLMFeeTableEventProvider:
    """Network LLM-backed raw JSONL event provider for fee table parsing."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    async def root_columns(self, source_view: FeeTableSourceView) -> str:
        return await asyncio.to_thread(self._run_task, "root_columns", source_view)

    async def categories(self, source_view: FeeTableSourceView, column_pool_json: str) -> str:
        return await asyncio.to_thread(
            self._run_task,
            "categories",
            source_view,
            column_pool_json=column_pool_json,
        )

    def _run_task(self, task: str, source_view: FeeTableSourceView, **variables: str) -> str:
        prompt = _render_prompt(task, source_view, **variables)
        llm_name = "vl" if source_view.content_type == "pdf_image" else "base"
        model = self.client.settings.model_for(llm_name)
        content = self.client.complete(
            prompt=prompt,
            model=model,
            llm_name=llm_name,
            image_url=source_view.visual_input if llm_name == "vl" else None,
            response_format=None,
        )
        jsonl = _normalize_jsonl_response(content)
        parse_raw_jsonl(jsonl, allowed_event_types=PROMPT_ALLOWED_EVENT_TYPES[task])
        return jsonl


def _render_prompt(task: str, source_view: FeeTableSourceView, **variables: str) -> str:
    task_prompt = PROMPTS[task]
    source_block = _source_block(source_view)
    variable_block = "\n".join(f"{key}: {value}" for key, value in variables.items() if value)
    if variable_block:
        variable_block = f"\nTask variables:\n{variable_block}\n"
    return f"{task_prompt}\n{variable_block}\n{source_block}".strip()


def _source_block(source_view: FeeTableSourceView) -> str:
    if source_view.content_type == "pdf_image":
        return (
            "Input type: pdf_image\n"
            "The image is attached as the vision input. Treat it as the cropped fee table section."
        )
    return (
        "Input type: excel_md\n"
        "Excel Markdown or semi-structured text:\n"
        f"{source_view.text_input or ''}"
    )


def _normalize_jsonl_response(content: str) -> str:
    text = _strip_markdown_fences(content.strip())
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(parsed, dict):
        return json.dumps(parsed, ensure_ascii=False)
    if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
        return "\n".join(json.dumps(item, ensure_ascii=False) for item in parsed)
    raise ValueError("LLM response must be JSONL events, a JSON event object, or a JSON event array")


def _strip_markdown_fences(text: str) -> str:
    match = re.fullmatch(r"```(?:jsonl|json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text
