from __future__ import annotations

import datetime
import secrets
import string
from enum import Enum, StrEnum
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def generate_id() -> str:
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M")
    random_suffix = ''.join(secrets.choice(string.digits) for _ in range(8))

    return timestamp + random_suffix


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
    is_sum: bool = False
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


class EdslSemiStructTerm(BaseModel):
    pass


class FeeCategoryInfo(BaseModel):
    fee_category_name: str
    pdf_field_name: str = ""
    category_type: Literal["charge", "free_unit", "financial_fee"] | None = None
    edsl_semi_struct: str = ""
    is_display_name: bool = True


class LoopInfo(BaseModel):
    is_loop: bool = False
    edsl_semi_struct: str = ""


class SummaryField(BaseModel):
    field_id: list[str] = Field(default_factory=list)
    field_name: str
    edsl_semi_struct: str = ""
    summary_type: Literal["count", "sum"] = "sum"
    is_virtual: bool = False


class SummaryInfo(BaseModel):
    summary_title: str
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=EdslSemiStructTerm)
    summary_fields: list[SummaryField] = Field(default_factory=list)
    is_display_title: bool = True


class ChildrenSortRule(BaseModel):
    is_sort: bool
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=EdslSemiStructTerm)


class ColumnsDefinition(BaseModel):
    field_id: str
    field_name: str
    cbs_name: str = ""
    is_sum: bool = False


class Column(BaseModel):
    field_id: str
    field_name: str
    edsl_semi_struct: EdslSemiStructTerm = Field(default_factory=EdslSemiStructTerm)
    is_sum: bool = False
    cbs_name: str = ""


class FeeType(str, Enum):
    charge = "charge"
    free_unit = "free_unit"
    financial_activity = "financial_activity"


class FeeCategoryType(str, Enum):
    parent = "parent"
    leaf = "leaf"
    root = "root"


class FeeCategoryTerm(BaseModel):
    fee_category_id: str = Field(default_factory=lambda: generate_id())
    fee_category_type: str
    seq: int
    fee_category_info: FeeCategoryInfo
    loop_info: LoopInfo | None = None
    summary_info: list[SummaryInfo] = Field(default_factory=list)
    children_sort_rule: ChildrenSortRule | None = None
    columns: list[Any] | None = None
    fee_type: FeeType | None = None
    reference_node_id: str | None = None
    columns_definition: list[ColumnsDefinition] | None = None
    children: list["FeeCategoryTerm"] | None = None
    closed: bool = False

    @model_validator(mode="after")
    def validate_conditions(self) -> "FeeCategoryTerm":
        if self.fee_category_type == FeeCategoryType.leaf:
            if self.columns is None:
                self.columns = []
            if self.fee_type is None:
                self.fee_type = FeeType.charge
        elif self.fee_category_type == FeeCategoryType.parent:
            if self.children is None:
                self.children = []
        elif self.fee_category_type == FeeCategoryType.root:
            if self.children is None:
                self.children = []
            if self.columns_definition is None:
                self.columns_definition = []
        return self


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
