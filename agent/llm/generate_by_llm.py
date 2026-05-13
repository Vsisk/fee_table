from typing import Any

from agent.llm.llm_client import LLMClient
from agent.llm.llm_post_processor import parse_json_response
from agent.llm.prompt_manager import prompt_manager as default_prompt_manager


def generate_by_llm(
    prompt_template: str,
    llm_name: str = "base",
    lang: str = "zh",
    *,
    client: LLMClient | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    llm_client = client or LLMClient()
    if not llm_client.is_usable:
        raise RuntimeError("LLM settings are not usable")

    manager = default_prompt_manager
    prompt_variables = dict(kwargs)
    image_base64 = prompt_variables.pop("image_base64", None)
    image_mime_type = prompt_variables.pop("image_mime_type", "image/png")
    prompt = manager.render(prompt_template, lang=lang, **prompt_variables)
    model = llm_client.settings.model_for(llm_name)

    payload: dict[str, Any] = {
        "prompt": prompt,
        "model": model,
        "llm_name": llm_name,
    }
    if llm_name == "vl":
        if not image_base64:
            raise ValueError("image_base64 is required when llm_name is vl")
        payload["image_url"] = f"data:{image_mime_type};base64,{image_base64}"
    elif llm_name != "base":
        raise ValueError(f"Unsupported llm_name: {llm_name}")

    content = llm_client.complete(**payload)
    try:
        return parse_json_response(content)
    except Exception as exc:
        raise ValueError(
            f"Failed to parse LLM response as dict for prompt_template={prompt_template}, "
            f"llm_name={llm_name}"
        ) from exc
