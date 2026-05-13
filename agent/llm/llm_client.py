from typing import Any

from openai import AuthenticationError, BadRequestError, OpenAI

from agent.llm.config import OpenAISettings, load_openai_settings

class LLMClient:
    def __init__(self, settings: OpenAISettings | None = None):
        self.settings = settings or load_openai_settings()
        self._client: OpenAI | None = None

    @property
    def is_usable(self) -> bool:
        return self.settings.is_usable

    def complete(
        self,
        *,
        prompt: str,
        model: str,
        llm_name: str = "base",
        image_url: str | None = None,
        response_format=None,
    ) -> str:
        if not self.is_usable:
            raise RuntimeError(
                "OpenAI settings are not usable. Check ENABLE_LLM and OPENAI_API_KEY in .env "
                "or environment variables."
            )

        user_content: str | list[dict[str, Any]]
        if llm_name == "vl":
            if not image_url:
                raise ValueError("image_url is required for vl payload")
            user_content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        elif llm_name == "base":
            user_content = prompt
        else:
            raise ValueError(f"Unsupported llm_name: {llm_name}")

        messages = [
            {
                "role": "system",
                "content": "You are a strict machine-readable API. Return only the requested format.",
            },
            {
                "role": "user",
                "content": user_content,
            },
        ]
        try:
            request: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": 0,
            }
            if response_format is not None:
                request["response_format"] = response_format
            response = self._get_client().chat.completions.create(**request)
        except AuthenticationError as exc:
            key_len = len(self.settings.api_key.strip())
            has_base_url = bool(self.settings.base_url)
            raise RuntimeError(
                "LLM authentication failed. The request was sent with "
                f"OPENAI_API_KEY length={key_len}, OPENAI_BASE_URL set={has_base_url}, "
                f"model={model!r}. Verify the key is valid for the configured base URL. "
                "For DashScope compatible mode, OPENAI_BASE_URL should usually be "
                "'https://dashscope.aliyuncs.com/compatible-mode/v1'."
            ) from exc
        except (TypeError, BadRequestError):
            response = self._get_client().chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
            )
        content = response.choices[0].message.content or "{}"
        return content

    def complete_json(self, prompt: str) -> dict[str, Any]:
        from agent.llm.llm_post_processor import parse_json_response

        content = self.complete(
            prompt=prompt,
            model=self.settings.model_for("base"),
            llm_name="base",
        )
        return parse_json_response(content)

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout_seconds,
            )
        return self._client
