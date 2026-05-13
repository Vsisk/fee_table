import json
import re
from typing import Any


JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_response(content: str) -> dict[str, Any]:
    text = content.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = JSON_OBJECT_PATTERN.search(text)
        if not match:
            raise
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed
