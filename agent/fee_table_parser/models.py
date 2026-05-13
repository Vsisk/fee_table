from __future__ import annotations

from enum import StrEnum
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ParseStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    DELETED = "deleted"


class FeeTableEventType(StrEnum):
    TABLE_PROFILE_DETECTED = "table_profile_detected"
    CATEGORY_DETECTED = "category_detected"
    COLUMN_DETECTED = "column_detected"
    COLUMNS_FINALIZED = "columns_finalized"
    LEAF_COLUMNS_BOUND = "leaf_columns_bound"
    CATEGORY_CLOSED = "category_closed"
    SUMMARY_DETECTED = "summary_detected"
    LOOP_RULE_DETECTED = "loop_rule_detected"
    SORT_RULE_DETECTED = "sort_rule_detected"
    RELATION_DETECTED = "relation_detected"
    SECTION_FINALIZED = "section_finalized"


class FeeTableParseInput(BaseModel):
    content_type: Literal["pdf_image", "excel_md"]
    image_url: str | None = None
    md: str | None = None

    @model_validator(mode="after")
    def require_matching_content(self) -> "FeeTableParseInput":
        if self.content_type == "pdf_image" and not self.image_url:
            raise ValueError("image_url is required for pdf_image input")
        if self.content_type == "excel_md" and not self.md:
            raise ValueError("md is required for excel_md input")
        return self


class FeeTableSourceView(BaseModel):
    content_type: Literal["pdf_image", "excel_md"]
    visual_input: str | None = None
    text_input: str | None = None


class MockLogicDataNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: Literal["simple_leaf"] = "simple_leaf"
    node_name: str
    annotation: str = "MOCK: generated from fee table column"
    mapping_status: Literal["pending"] = "pending"


class ColumnTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str
    column_key: str
    pdf_example: str
    pdf_field_name: str = ""
    edsl_semi_struct: str = ""
    logic_data_node: MockLogicDataNode | None = None

    @model_validator(mode="after")
    def normalize_column(self) -> "ColumnTerm":
        self.edsl_semi_struct = ""
        if self.logic_data_node is None:
            self.logic_data_node = MockLogicDataNode(
                node_id=f"mock_{self.field_id}",
                node_name=self.column_key,
            )
        return self


class FeeCategoryInfo(BaseModel):
    fee_category_name: str
    pdf_field_name: str = ""
    category_type: Literal["charge", "free_unit", "financial_fee"] | None = None
    edsl_semi_struct: str = ""
    is_display_name: bool = True

    @model_validator(mode="after")
    def clear_edsl(self) -> "FeeCategoryInfo":
        self.edsl_semi_struct = ""
        return self


class SummaryField(BaseModel):
    field_id: list[str] = Field(default_factory=list)
    field_name: str
    edsl_semi_struct: str = ""
    summary_type: str = "sum"
    is_virtual: bool = False

    @model_validator(mode="after")
    def clear_edsl(self) -> "SummaryField":
        self.edsl_semi_struct = ""
        return self


class SummaryInfo(BaseModel):
    summary_title: str
    is_display_title: bool = True
    edsl_semi_struct: str = ""
    summary_fields: list[SummaryField] = Field(default_factory=list)

    @model_validator(mode="after")
    def clear_edsl(self) -> "SummaryInfo":
        self.edsl_semi_struct = ""
        return self


class LoopInfo(BaseModel):
    is_loop: bool = False
    edsl_semi_struct: str = ""

    @model_validator(mode="after")
    def clear_edsl(self) -> "LoopInfo":
        self.edsl_semi_struct = ""
        return self


class ChildrenSortRule(BaseModel):
    is_sort: bool = True
    edsl_semi_struct: str = ""
    sort_basis: str = "display_order"

    @model_validator(mode="after")
    def clear_edsl(self) -> "ChildrenSortRule":
        self.edsl_semi_struct = ""
        return self


class FeeCategoryTerm(BaseModel):
    fee_category_id: str
    fee_category_type: Literal["parent", "leaf"]
    seq: int
    fee_category_info: FeeCategoryInfo
    children: list["FeeCategoryTerm"] = Field(default_factory=list)
    columns: list[ColumnTerm | str] = Field(default_factory=list)
    summary_info: list[SummaryInfo] = Field(default_factory=list)
    loop_info: LoopInfo | None = None
    children_sort_rule: ChildrenSortRule | None = None
    closed: bool = False


class CrossRelation(BaseModel):
    relation_id: str
    relation_type: str
    source_category_ids: list[str] = Field(default_factory=list)
    target_category_id: str | None = None
    description: str = ""


class FeeTable(BaseModel):
    fee_category_tree: FeeCategoryTerm


class FeeTableLogicArea(BaseModel):
    source_view: FeeTableSourceView | None = None
    fee_table: FeeTable
    table_profile: dict[str, Any] = Field(default_factory=dict)
    relations: list[CrossRelation] = Field(default_factory=list)
    parse_status: Literal["draft", "finalized"] = "draft"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="allow")


class FeeTableEvent(BaseModel):
    event_type: FeeTableEventType
    event_id: str
    parent_id: str | None = None
    target_id: str | None = None
    seq: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence: Evidence = Field(default_factory=Evidence)
    status: ParseStatus = ParseStatus.DRAFT


def normalize_field_name(field_name: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", field_name.strip()) if part]
    if not parts:
        return "unknown"
    first = parts[0].lower()
    rest = [part[:1].upper() + part[1:].lower() for part in parts[1:]]
    return "".join([first, *rest])
