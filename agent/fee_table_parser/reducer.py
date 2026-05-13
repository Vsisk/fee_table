from __future__ import annotations

from dataclasses import dataclass, field
import json

from agent.fee_table_parser.event_schema import (
    CATEGORY_EVENT_TYPES,
    COLUMN_EVENT_TYPES,
    RawFeeTableEvent,
    parse_raw_jsonl,
)
from agent.fee_table_parser.id_generator import FeeTableIdGenerator
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
        id_generator: FeeTableIdGenerator | None = None,
    ) -> None:
        self.source_view = source_view
        self.id_generator = id_generator or FeeTableIdGenerator()
        self.root = None
        self._root_columns: list[ColumnTerm] = []
        self._path_to_category: dict[tuple[str, ...], FeeCategoryTerm] = {}
        self._explicit_paths: set[tuple[str, ...]] = set()
        self._auto_paths: set[tuple[str, ...]] = set()
        self._open_paths: set[tuple[str, ...]] = set()
        self._closed_paths: set[tuple[str, ...]] = set()
        self._pending_leaf_bindings: list[RawFeeTableEvent] = []
        self._pending_category_closes: list[RawFeeTableEvent] = []
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
        if event.event_type == FeeTableEventType.CATEGORY_DETECTED:
            result = self._apply_raw_category_detected(event)
            result.extend(self._drain_pending())
            return result
        if event.event_type == FeeTableEventType.LEAF_COLUMNS_BOUND:
            result = self._apply_raw_leaf_columns_bound_or_pending(event)
            result.extend(self._drain_pending())
            return result
        if event.event_type == FeeTableEventType.CATEGORY_CLOSED:
            result = self._apply_raw_category_closed_or_pending(event)
            result.extend(self._drain_pending())
            return result
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
                "pdf_field_name": column.pdf_field_name,
            }
            for column in self._root_columns
        ]
        return json.dumps(payload, ensure_ascii=False)

    def finalize_category_stream(self) -> ReducerApplyResult:
        result = self._drain_pending()
        unresolved_closes = [event.payload["path"] for event in self._pending_category_closes]
        unresolved_bindings = [event.payload["path"] for event in self._pending_leaf_bindings]
        if unresolved_closes:
            raise ValueError(f"pending category_closed events could not be resolved: {unresolved_closes}")
        if unresolved_bindings:
            raise ValueError(f"pending leaf_columns_bound events could not be resolved: {unresolved_bindings}")
        if self._open_paths:
            raise ValueError(f"category paths were detected but not closed: {sorted(self._open_paths)}")
        return result

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
        column_key = event.payload["column_key"]
        pdf_field_name = event.payload["pdf_field_name"]
        signature = (column_key, pdf_field_name)
        if signature in self._column_signature_to_field_id:
            return

        final_key = self._next_column_key(column_key, pdf_field_name)
        column = ColumnTerm(
            field_id=self.id_generator.new_id(),
            column_key=final_key,
            pdf_example=event.payload["pdf_example"],
            pdf_field_name=pdf_field_name,
        )
        self._root_columns.append(column)
        self._root_columns.sort(key=lambda item: item.field_id)
        if self.root is not None:
            self.root.columns_definition = self._columns_definition()
        self._column_signature_to_field_id[signature] = column.field_id

    def _next_column_key(self, column_key: str, pdf_field_name: str) -> str:
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

    def _apply_raw_category_detected(self, event: RawFeeTableEvent) -> ReducerApplyResult:
        path = tuple(event.payload["path"])
        if path in self._explicit_paths:
            raise ValueError(f"duplicate category path: {path}")
        if self.root is None:
            return self._apply_first_raw_category_detected(event, path)
        self._ensure_parent_paths(path)
        parent = self._parent_for_path(path)
        seq = len(parent.children) + 1
        pdf_name = event.payload.get("pdf_field_name", "")
        category = FeeCategoryTerm(
            fee_category_type=event.payload["fee_category_type"],
            seq=seq,
            fee_category_info=FeeCategoryInfo(
                fee_category_name=event.payload["fee_category_name"],
                pdf_field_name=pdf_name,
                category_type=event.payload.get("category_type"),
                is_display_name=True if pdf_name else False,
            ),
        )
        parent.children.append(category)
        self._path_to_category[path] = category
        self._explicit_paths.add(path)
        self._open_paths.add(path)
        return ReducerApplyResult()

    def _apply_first_raw_category_detected(
        self,
        event: RawFeeTableEvent,
        path: tuple[str, ...],
    ) -> ReducerApplyResult:
        if event.payload["fee_category_type"] == "leaf":
            pdf_name = event.payload.get("pdf_field_name", "")
            self.root = FeeCategoryTerm(
                fee_category_type="leaf",
                seq=0,
                fee_category_info=FeeCategoryInfo(
                    fee_category_name=event.payload["fee_category_name"],
                    pdf_field_name=pdf_name,
                    category_type=event.payload.get("category_type"),
                    is_display_name=True if pdf_name else False,
                ),
                columns_definition=self._columns_definition(),
            )
            self._path_to_category[path] = self.root
            self._explicit_paths.add(path)
            self._open_paths.add(path)
            return ReducerApplyResult()

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
        return self._apply_raw_category_detected(event)

    def _columns_definition(self) -> list[ColumnsDefinition]:
        return [
            ColumnsDefinition(
                field_id=column.field_id,
                field_name=column.column_key,
                cbs_name=column.pdf_field_name,
                is_sum=column.is_sum,
            )
            for column in self._root_columns
        ]

    def _ensure_parent_paths(self, path: tuple[str, ...]) -> None:
        for index in range(1, len(path)):
            parent_path = path[:index]
            if parent_path in self._path_to_category:
                continue
            parent = self._parent_for_path(parent_path)
            category = FeeCategoryTerm(
                fee_category_id=self.id_generator.new_id(),
                fee_category_type="parent",
                seq=len(parent.children) + 1,
                fee_category_info=FeeCategoryInfo(
                    fee_category_name=parent_path[-1],
                    pdf_field_name=parent_path[-1],
                    is_display_name=True,
                ),
            )
            parent.children.append(category)
            self._path_to_category[parent_path] = category
            self._auto_paths.add(parent_path)

    def _parent_for_path(self, path: tuple[str, ...]) -> FeeCategoryTerm:
        if self.root is None:
            raise ValueError("root category has not been initialized")
        if len(path) == 1:
            return self.root
        parent_path = path[:-1]
        if parent_path not in self._path_to_category:
            raise ValueError(f"missing parent path: {parent_path}")
        return self._path_to_category[parent_path]

    def _apply_raw_leaf_columns_bound_or_pending(self, event: RawFeeTableEvent) -> ReducerApplyResult:
        if self._apply_raw_leaf_columns_bound(event):
            return ReducerApplyResult()
        self._pending_leaf_bindings.append(event)
        return ReducerApplyResult()

    def _apply_raw_leaf_columns_bound(self, event: RawFeeTableEvent) -> bool:
        path = tuple(event.payload["path"])
        if path not in self._path_to_category:
            return False
        category = self._path_to_category[path]
        if category.fee_category_type != "leaf":
            raise ValueError(f"leaf_columns_bound target is not a leaf: {path}")
        root_field_ids = {column.field_id for column in self._root_columns}
        field_ids = sorted(set(event.payload["field_ids"]))
        missing = [field_id for field_id in field_ids if field_id not in root_field_ids]
        if missing:
            raise ValueError(f"leaf_columns_bound references unknown root column field_id: {missing}")
        category.columns = field_ids
        return True

    def _apply_raw_category_closed_or_pending(self, event: RawFeeTableEvent) -> ReducerApplyResult:
        result = self._apply_raw_category_closed(event)
        if result is not None:
            return result
        self._pending_category_closes.append(event)
        return ReducerApplyResult()

    def _apply_raw_category_closed(self, event: RawFeeTableEvent) -> ReducerApplyResult | None:
        path = tuple(event.payload["path"])
        if path not in self._path_to_category:
            return None
        if path in self._closed_paths:
            raise ValueError(f"category path is already closed: {path}")
        open_descendants = [
            candidate for candidate in self._open_paths if len(candidate) > len(path) and candidate[: len(path)] == path
        ]
        if open_descendants:
            return None
        category = self._path_to_category[path]
        category.closed = True
        self._closed_paths.add(path)
        self._open_paths.discard(path)
        result = ReducerApplyResult(closed_category_ids=[category.fee_category_id])
        result.extend(self._close_auto_ancestors())
        return result

    def _close_auto_ancestors(self) -> ReducerApplyResult:
        result = ReducerApplyResult()
        changed = True
        while changed:
            changed = False
            for path in sorted(self._auto_paths - self._closed_paths, key=len, reverse=True):
                open_descendants = [
                    candidate
                    for candidate in self._open_paths
                    if len(candidate) > len(path) and candidate[: len(path)] == path
                ]
                if open_descendants:
                    continue
                category = self._path_to_category[path]
                category.closed = True
                self._closed_paths.add(path)
                changed = True
        return result

    def _drain_pending(self) -> ReducerApplyResult:
        result = ReducerApplyResult()
        progressed = True
        while progressed:
            progressed = False
            remaining_bindings: list[RawFeeTableEvent] = []
            for event in self._pending_leaf_bindings:
                if self._apply_raw_leaf_columns_bound(event):
                    progressed = True
                else:
                    remaining_bindings.append(event)
            self._pending_leaf_bindings = remaining_bindings

            remaining_closes: list[RawFeeTableEvent] = []
            for event in self._pending_category_closes:
                close_result = self._apply_raw_category_closed(event)
                if close_result is None:
                    remaining_closes.append(event)
                else:
                    result.extend(close_result)
                    progressed = True
            self._pending_category_closes = remaining_closes
        return result
