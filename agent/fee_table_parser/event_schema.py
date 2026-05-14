from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.fee_table_parser.models import FeeTableEventType, ParseStatus


COLUMN_EVENT_TYPES = {
    FeeTableEventType.COLUMN_DETECTED,
    FeeTableEventType.COLUMNS_FINALIZED,
}

CATEGORY_EVENT_TYPES = {
    FeeTableEventType.CATEGORY_OPEN,
    FeeTableEventType.CATEGORY_LEAF,
    FeeTableEventType.CATEGORY_CLOSE,
    FeeTableEventType.SUMMARY_DETECTED,
}

PROMPT_ALLOWED_EVENT_TYPES: dict[str, set[FeeTableEventType]] = {
    "root_columns": COLUMN_EVENT_TYPES,
    "categories": CATEGORY_EVENT_TYPES,
}


class RawColumnDetectedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cbs_key: str
    pdf_exp: str
    pdf_key: str
    is_sum: bool = False


class RawColumnsFinalizedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawCategoryOpenPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fee_category_name: str
    pdf_key: str = ""

    @model_validator(mode="after")
    def validate_category_open_payload(self) -> "RawCategoryOpenPayload":
        if not self.fee_category_name.strip():
            raise ValueError("fee_category_name must not be empty")
        return self


class RawCategoryLeafPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fee_category_name: str
    pdf_key: str = ""
    category_type: Literal["charge", "free_unit", "financial_fee"]
    field_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_category_leaf_payload(self) -> "RawCategoryLeafPayload":
        if not self.fee_category_name.strip():
            raise ValueError("fee_category_name must not be empty")
        return self


class RawCategoryClosePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RawSummaryDetectedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_title: str
    summary_type: Literal["count", "sum"]
    field_id: list[str | list[str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_summary_detected_payload(self) -> "RawSummaryDetectedPayload":
        if not self.summary_title.strip():
            raise ValueError("summary_title must not be empty")
        if not self.field_id:
            raise ValueError("field_id must not be empty")
        normalized_field_id: list[str | list[str]] = []
        for item in self.field_id:
            if isinstance(item, str):
                if not item.strip():
                    raise ValueError("field_id entries must not be empty")
                normalized_field_id.append(item)
                continue
            if not item:
                raise ValueError("grouped field_id entries must not be empty")
            if any(not field_id.strip() for field_id in item):
                raise ValueError("grouped field_id entries must not contain empty values")
            normalized_field_id.append(item)
        self.field_id = normalized_field_id
        return self


RAW_PAYLOAD_SCHEMAS: dict[FeeTableEventType, type[BaseModel]] = {
    FeeTableEventType.COLUMN_DETECTED: RawColumnDetectedPayload,
    FeeTableEventType.COLUMNS_FINALIZED: RawColumnsFinalizedPayload,
    FeeTableEventType.CATEGORY_OPEN: RawCategoryOpenPayload,
    FeeTableEventType.CATEGORY_LEAF: RawCategoryLeafPayload,
    FeeTableEventType.CATEGORY_CLOSE: RawCategoryClosePayload,
    FeeTableEventType.SUMMARY_DETECTED: RawSummaryDetectedPayload,
}


def parse_raw_jsonl(
    jsonl: str,
    allowed_event_types: set[FeeTableEventType] | None = None,
) -> list["RawFeeTableEvent"]:
    events: list[RawFeeTableEvent] = []
    for line_number, line in enumerate(jsonl.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        event = RawFeeTableEvent.model_validate(json.loads(stripped))
        if allowed_event_types is not None and event.event_type not in allowed_event_types:
            raise ValueError(f"event_type {event.event_type} is not allowed on line {line_number}")
        events.append(event)
    return events


class RawFeeTableEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: FeeTableEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    status: ParseStatus = ParseStatus.CONFIRMED

    @model_validator(mode="after")
    def validate_raw_event(self) -> "RawFeeTableEvent":
        if self.status != ParseStatus.CONFIRMED:
            raise ValueError("Only confirmed raw events are supported in v1")
        if self.event_type not in RAW_PAYLOAD_SCHEMAS:
            raise ValueError(f"raw event_type {self.event_type} is not supported")
        schema = RAW_PAYLOAD_SCHEMAS[self.event_type]
        self.payload = schema.model_validate(self.payload).model_dump()
        return self
