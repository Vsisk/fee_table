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
    FeeTableEventType.CATEGORY_DETECTED,
    FeeTableEventType.LEAF_COLUMNS_BOUND,
    FeeTableEventType.CATEGORY_CLOSED,
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


class RawCategoryDetectedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: list[str]
    fee_category_name: str
    fee_category_type: Literal["parent", "leaf"]
    pdf_field_name: str = ""
    category_type: Literal["charge", "free_unit", "financial_fee"] | None = None

    @model_validator(mode="after")
    def validate_category_payload(self) -> "RawCategoryDetectedPayload":
        _validate_path(self.path)
        if self.fee_category_name != self.path[-1]:
            raise ValueError("fee_category_name must match the last path item")
        if self.fee_category_type == "leaf" and self.category_type is None:
            raise ValueError("leaf category_detected requires category_type")
        if self.fee_category_type == "parent" and self.category_type is not None:
            raise ValueError("parent category_detected must not contain category_type")
        return self


class RawLeafColumnsBoundPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: list[str]
    field_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_path(self) -> "RawLeafColumnsBoundPayload":
        _validate_path(self.path)
        return self


class RawCategoryClosedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: list[str]

    @model_validator(mode="after")
    def validate_path(self) -> "RawCategoryClosedPayload":
        _validate_path(self.path)
        return self


RAW_PAYLOAD_SCHEMAS: dict[FeeTableEventType, type[BaseModel]] = {
    FeeTableEventType.COLUMN_DETECTED: RawColumnDetectedPayload,
    FeeTableEventType.COLUMNS_FINALIZED: RawColumnsFinalizedPayload,
    FeeTableEventType.CATEGORY_DETECTED: RawCategoryDetectedPayload,
    FeeTableEventType.LEAF_COLUMNS_BOUND: RawLeafColumnsBoundPayload,
    FeeTableEventType.CATEGORY_CLOSED: RawCategoryClosedPayload,
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


def _validate_path(path: list[str]) -> None:
    if not path:
        raise ValueError("path must not be empty")
    if any(not item.strip() for item in path):
        raise ValueError("path items must not be empty")
