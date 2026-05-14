from __future__ import annotations

from agent.fee_table_parser.event_schema import PROMPT_ALLOWED_EVENT_TYPES


COMMON_JSONL_RULES = """
Output JSONL only. Do not return Markdown, prose, or a complete logic_area.
Each line must be one complete JSON object.
Do not output ids: no event_id, target_id, parent_id, or fee_category_id.
Use status only if needed; v1 supports confirmed events only.
Never output data_source, expression, BO, context, function, resource_id, XML path, mapping_tree, or path.
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
Allowed events: category_open, category_leaf, category_close, summary_detected.
Do not output payload.path. Code maintains the hierarchy with a stack.
category_open enters a parent category; payload must contain fee_category_name and may contain pdf_key.
category_leaf emits a leaf category; payload must contain fee_category_name, category_type, and field_ids copied from the provided root column pool.
summary_detected emits one visible summary row for a category; payload must contain summary_title, summary_type (sum or count), and field_id.
For a summary column that does not exist in the root column pool but is calculated from multiple root columns, output one grouped field_id entry such as [["vat_id", "amount_id"]].
Emit a parent category's summary_detected immediately after its category_open, before its children. Emit a leaf category's summary_detected immediately after its category_leaf.
category_close leaves the current parent category; payload must be empty.
Every category_open must have one explicit category_close after all children have been emitted.
If the whole fee table has only one leaf category at the root, output exactly one category_leaf and no category_open/category_close.
Do not output category_detected, leaf_columns_bound, category_closed, loop_rule_detected, sort_rule_detected, relation_detected, or section_finalized.
""".strip(),
}


__all__ = ["PROMPTS", "PROMPT_ALLOWED_EVENT_TYPES"]
