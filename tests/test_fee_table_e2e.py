import base64
import json
import os
from pathlib import Path

import pytest

from agent.fee_table_parser.models import FeeTableParseInput
from agent.fee_table_parser.parser import FeeTableLogicAreaParser
from agent.llm.config import PROJECT_ROOT, load_openai_settings


@pytest.mark.e2e
def test_real_llm_fee_table_image_end_to_end():
    settings = load_openai_settings()
    if os.environ.get("RUN_LLM_E2E") != "1":
        pytest.skip("Set RUN_LLM_E2E=1 to run the real network LLM e2e test")
    if not settings.is_usable:
        pytest.skip("OPENAI_API_KEY is required for the real network LLM e2e test")

    image_url = os.environ.get("E2E_FEE_TABLE_IMAGE_URL") or _local_case_image_data_url()
    parser = FeeTableLogicAreaParser.from_settings(settings)

    logic_area = parser.parse_fee_table_logic_area(
        FeeTableParseInput(content_type="pdf_image", image_url=image_url)
    )

    assert logic_area.parse_status == "finalized"
    root = logic_area.fee_table.fee_category_tree
    assert root.fee_category_id == "fee_table_root"
    assert root.columns
    assert root.children
    root_field_ids = {column.field_id for column in root.columns}
    leaf_columns = _leaf_column_refs(root)
    assert leaf_columns
    assert all(field_id in root_field_ids for field_id in leaf_columns)
    assert _empty_enrichment_fields(root)


def _local_case_image_data_url() -> str:
    image_path = PROJECT_ROOT / "case.jpg"
    if not image_path.exists():
        pytest.skip("case.jpg is required unless E2E_FEE_TABLE_IMAGE_URL is set")
    encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _leaf_column_refs(category) -> list[str]:
    if category.fee_category_type == "leaf":
        return list(category.columns)
    refs: list[str] = []
    for child in category.children:
        refs.extend(_leaf_column_refs(child))
    return refs


def _empty_enrichment_fields(category) -> bool:
    if category.summary_info != []:
        return False
    if category.loop_info is not None:
        return False
    if category.children_sort_rule is not None:
        return False
    return all(_empty_enrichment_fields(child) for child in category.children)


def _all_edsl_empty(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "edsl_semi_struct" and item != "":
                return False
            if not _all_edsl_empty(item):
                return False
    if isinstance(value, list):
        return all(_all_edsl_empty(item) for item in value)
    return True
