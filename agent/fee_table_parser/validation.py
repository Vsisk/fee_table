from __future__ import annotations

from agent.fee_table_parser.models import CrossRelation, FeeCategoryTerm


def validate_fee_category_tree(
    root: FeeCategoryTerm,
    relations: list[CrossRelation] | None = None,
) -> None:
    category_ids: set[str] = set()
    root_field_ids = _validate_root_columns_definition(root)
    _validate_category(root, category_ids, root_field_ids, is_root=True)
    for relation in relations or []:
        for category_id in relation.source_category_ids:
            if category_id not in category_ids:
                raise ValueError(f"relation source_category_ids references unknown category: {category_id}")
        if relation.target_category_id and relation.target_category_id not in category_ids:
            raise ValueError(f"relation target_category_id references unknown category: {relation.target_category_id}")


def _validate_root_columns_definition(root: FeeCategoryTerm) -> set[str]:
    field_ids: set[str] = set()
    field_names: set[str] = set()
    for column in root.columns_definition or []:
        if column.field_id in field_ids:
            raise ValueError(f"field_id must be unique: {column.field_id}")
        if column.field_name in field_names:
            raise ValueError(f"field_name must be unique after suffixing: {column.field_name}")
        field_ids.add(column.field_id)
        field_names.add(column.field_name)
    return field_ids


def _validate_category(
    category: FeeCategoryTerm,
    category_ids: set[str],
    root_field_ids: set[str],
    *,
    is_root: bool = False,
) -> None:
    if category.fee_category_id in category_ids:
        raise ValueError(f"category_id must be unique: {category.fee_category_id}")
    category_ids.add(category.fee_category_id)

    if category.fee_category_type == "parent":
        if category.fee_category_info.category_type is not None:
            raise ValueError("parent category must not contain category_type")
        if not is_root and category.columns:
            raise ValueError("non-root parent category cannot contain columns")
    if category.fee_category_type == "leaf":
        if category.fee_category_info.category_type is None:
            raise ValueError("leaf category requires category_type")
        if category.children:
            raise ValueError("leaf category cannot contain children")
        for field_id in category.columns or []:
            if not isinstance(field_id, str):
                raise ValueError("leaf columns must contain root field_id strings")
            if field_id not in root_field_ids:
                raise ValueError(f"leaf columns reference unknown root column field_id: {field_id}")

    seen_child_seq: set[int] = set()
    for child in category.children or []:
        if child.seq in seen_child_seq:
            raise ValueError(f"same parent cannot contain duplicate category seq: {child.seq}")
        seen_child_seq.add(child.seq)
        _validate_category(child, category_ids, root_field_ids)

    scoped_leaf_fields = _collect_leaf_field_ids(category)
    for summary in category.summary_info:
        for summary_field in summary.summary_fields:
            if not summary_field.is_virtual:
                for field_id in summary_field.field_id:
                    if field_id not in scoped_leaf_fields:
                        raise ValueError(f"summary field_id is not referenced by scoped leaf columns: {field_id}")


def _collect_leaf_field_ids(category: FeeCategoryTerm) -> set[str]:
    if category.fee_category_type == "leaf":
        return {field_id for field_id in category.columns or [] if isinstance(field_id, str)}
    field_ids: set[str] = set()
    for child in category.children or []:
        field_ids.update(_collect_leaf_field_ids(child))
    return field_ids
