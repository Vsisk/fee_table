from __future__ import annotations

from agent.fee_table_parser.event_schema import PROMPT_ALLOWED_EVENT_TYPES


COMMON_JSONL_RULES = """
Output JSONL only. Do not return Markdown, prose, or a complete logic_area.
Each line must be one complete JSON object.
Do not output ids: no event_id, target_id, parent_id, fee_category_id, or field_id unless the field_id is copied from the provided root column pool in a leaf_columns_bound event.
Use status only if needed; v1 supports confirmed events only.
Never output data_source, expression, BO, context, function, resource_id, XML path, or mapping_tree.
Every edsl_semi_struct must be omitted.
""".strip()


PROMPTS = {
    "root_columns": f"""
{COMMON_JSONL_RULES}
Task: identify the fee attribute column pool for the whole fee table area.
Allowed events: column_detected, columns_finalized.
column_detected.payload must contain column_key, pdf_example, pdf_field_name.
column_key should be a stable semantic key such as amount, total_amount, duration, description, group.
Do not output category events.
End with exactly one columns_finalized event.
""".strip(),
    "categories": f"""
{COMMON_JSONL_RULES}
Task: identify the fee category tree and bind leaf categories to the provided root column field_ids.
Allowed events: category_detected, leaf_columns_bound, category_closed.
Use payload.path as the category identity and hierarchy.
category_detected.payload must contain path, fee_category_name, fee_category_type.
For leaf category_detected, category_type is required and must be one of charge, free_unit, financial_fee.
For parent category_detected, category_type must be omitted.
leaf_columns_bound.payload must contain path and field_ids copied from the provided root column pool.
category_closed.payload must contain path.
Do not output summary_detected, loop_rule_detected, sort_rule_detected, relation_detected, or section_finalized.
Every explicit category_detected must have one category_closed.
""".strip(),
}


__all__ = ["PROMPTS", "PROMPT_ALLOWED_EVENT_TYPES"]
