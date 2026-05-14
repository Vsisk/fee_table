from __future__ import annotations

from dataclasses import dataclass, field
import json

from agent.fee_table_parser.event_schema import (
    RawFeeTableEvent,
    parse_raw_jsonl,
)
from agent.fee_table_parser.models import (
    ColumnTerm,
    ColumnsDefinition,
    CrossRelation,
    FeeCategoryInfo,
    FeeCategoryTerm,
    FeeTable,
    FeeTableEventType,
    FeeTableLogicArea,
    FeeTableSourceView,
)
from agent.fee_table_parser.validation import validate_fee_category_tree


@dataclass
class ReducerApplyResult:
    closed_category_ids: list[str] = field(default_factory=list)

    def extend(self, other: "ReducerApplyResult") -> None:
        self.closed_category_ids.extend(other.closed_category_ids)


class FeeTableStreamReducer:
    def __init__(
        self,
        source_view: FeeTableSourceView | None = None,
    ) -> None:
        self.source_view = source_view
        self.root = None
        self._category_stack: list[FeeCategoryTerm] = []
        self._root_columns: list[ColumnTerm] = []
        self._columns_finalized = False
        self._column_keys_by_original: dict[str, set[str]] = {}
        self._column_signature_to_field_id: dict[tuple[str, str], str] = {}
        self._relations: list[CrossRelation] = []
        self._section_finalized = False

    @property
    def columns_finalized(self) -> bool:
        return self._columns_finalized

    def consume_raw_jsonl(
        self,
        jsonl: str,
        allowed_event_types: set[FeeTableEventType] | None = None,
    ) -> ReducerApplyResult:
        result = ReducerApplyResult()
        for event in parse_raw_jsonl(jsonl, allowed_event_types):
            result.extend(self.consume_raw_event(event))
        return result

    def consume_raw_event(self, event: RawFeeTableEvent) -> ReducerApplyResult:
        if event.event_type == FeeTableEventType.COLUMN_DETECTED:
            self._apply_raw_column_detected(event)
            return ReducerApplyResult()
        if event.event_type == FeeTableEventType.COLUMNS_FINALIZED:
            self._columns_finalized = True
            return ReducerApplyResult()
        if event.event_type == FeeTableEventType.CATEGORY_OPEN:
            return self._apply_raw_category_open(event)
        if event.event_type == FeeTableEventType.CATEGORY_LEAF:
            return self._apply_raw_category_leaf(event)
        if event.event_type == FeeTableEventType.CATEGORY_CLOSE:
            return self._apply_raw_category_close()
        raise ValueError(f"unsupported raw event_type: {event.event_type}")

    def ensure_columns_finalized(self) -> None:
        if not self._columns_finalized:
            raise ValueError("columns_finalized event is required before category parsing")

    def column_pool_prompt_json(self) -> str:
        payload = [
            {
                "field_id": column.field_id,
                "column_key": column.column_key,
                "pdf_example": column.pdf_example,
                "pdf_key": column.pdf_field_name,
            }
            for column in self._root_columns
        ]
        return json.dumps(payload, ensure_ascii=False)

    def finalize_category_stream(self) -> ReducerApplyResult:
        if len(self._category_stack) > 1:
            names = [
                category.fee_category_info.fee_category_name
                for category in self._category_stack[1:]
            ]
            raise ValueError(f"category stack has unclosed parent categories: {names}")
        return ReducerApplyResult()

    def _apply_raw_category_open(self, event: RawFeeTableEvent) -> ReducerApplyResult:
        self._ensure_stack_root()
        parent = self._category_stack[-1]
        category = FeeCategoryTerm(
            fee_category_type="parent",
            seq=len(parent.children) + 1,
            fee_category_info=FeeCategoryInfo(
                fee_category_name=event.payload["fee_category_name"],
                pdf_field_name=event.payload.get("pdf_key", ""),
                is_display_name=bool(event.payload.get("pdf_key", "")),
            ),
        )
        parent.children.append(category)
        self._category_stack.append(category)
        return ReducerApplyResult()

    def _apply_raw_category_leaf(self, event: RawFeeTableEvent) -> ReducerApplyResult:
        field_ids = self._validated_root_field_ids(event.payload["field_ids"])
        if self.root is None:
            self.root = FeeCategoryTerm(
                fee_category_type="leaf",
                seq=0,
                fee_category_info=FeeCategoryInfo(
                    fee_category_name=event.payload["fee_category_name"],
                    pdf_field_name=event.payload.get("pdf_key", ""),
                    category_type=event.payload["category_type"],
                    is_display_name=bool(event.payload.get("pdf_key", "")),
                ),
                columns_definition=self._columns_definition(),
                columns=field_ids,
            )
            self.root.closed = True
            return ReducerApplyResult(closed_category_ids=[self.root.fee_category_id])

        if self.root.fee_category_type == "leaf":
            raise ValueError("cannot append category events after a leaf root has been created")

        parent = self._category_stack[-1]
        category = FeeCategoryTerm(
            fee_category_type="leaf",
            seq=len(parent.children) + 1,
            fee_category_info=FeeCategoryInfo(
                fee_category_name=event.payload["fee_category_name"],
                pdf_field_name=event.payload.get("pdf_key", ""),
                category_type=event.payload["category_type"],
                is_display_name=bool(event.payload.get("pdf_key", "")),
            ),
            columns=field_ids,
        )
        parent.children.append(category)
        category.closed = True
        return ReducerApplyResult(closed_category_ids=[category.fee_category_id])

    def _apply_raw_category_close(self) -> ReducerApplyResult:
        if not self._category_stack or len(self._category_stack) == 1:
            raise ValueError("category_close requires an open parent category")
        category = self._category_stack.pop()
        category.closed = True
        return ReducerApplyResult(closed_category_ids=[category.fee_category_id])

    def _ensure_stack_root(self) -> None:
        if self.root is None:
            self.root = FeeCategoryTerm(
                fee_category_type="root",
                seq=0,
                fee_category_info=FeeCategoryInfo(
                    fee_category_name="fee_table_root",
                    pdf_field_name="",
                    is_display_name=False,
                ),
                columns_definition=self._columns_definition(),
            )
            self._category_stack = [self.root]
            return
        if self.root.fee_category_type == "leaf":
            raise ValueError("cannot open a parent category after a leaf root has been created")
        if not self._category_stack:
            self._category_stack = [self.root]

    def _validated_root_field_ids(self, field_ids: list[str]) -> list[str]:
        root_field_ids = {column.field_id for column in self._root_columns}
        normalized_field_ids = sorted(set(field_ids))
        missing = [field_id for field_id in normalized_field_ids if field_id not in root_field_ids]
        if missing:
            raise ValueError(f"category_leaf references unknown root column field_id: {missing}")
        return normalized_field_ids

    def finalize_section(self) -> FeeTableLogicArea:
        validate_fee_category_tree(self.root, self._relations)
        self._section_finalized = True
        return FeeTableLogicArea(
            source_view=self.source_view,
            fee_table=FeeTable(fee_category_tree=self.root),
            relations=self._relations,
            parse_status="finalized",
        )

    def _apply_raw_column_detected(self, event: RawFeeTableEvent) -> None:
        if self._columns_finalized:
            return
        column_key = event.payload["cbs_key"]
        pdf_key = event.payload["pdf_key"]
        signature = (column_key, pdf_key)
        if signature in self._column_signature_to_field_id:
            return

        final_key = self._next_column_key(column_key, pdf_key)
        column = ColumnTerm(
            column_key=final_key,
            pdf_example=event.payload["pdf_exp"],
            pdf_field_name=pdf_key,
        )
        self._root_columns.append(column)
        self._root_columns.sort(key=lambda item: item.field_id)
        if self.root is not None:
            self.root.columns_definition = self._columns_definition()
        self._column_signature_to_field_id[signature] = column.field_id

    def _next_column_key(self, column_key: str, pdf_key: str) -> str:
        existing = self._column_keys_by_original.setdefault(column_key, set())
        if not existing:
            existing.add(column_key)
            return column_key
        suffix = 2
        while True:
            candidate = f"{column_key}_{suffix}"
            if candidate not in existing:
                existing.add(candidate)
                return candidate
            suffix += 1

    def _columns_definition(self) -> list[ColumnsDefinition]:
        return [
            ColumnsDefinition(
                field_id=column.field_id,
                field_name=column.pdf_field_name,
                cbs_name=column.column_key,
                is_sum=column.is_sum,
            )
            for column in self._root_columns
        ]
