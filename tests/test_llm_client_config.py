from pathlib import Path

from agent.llm.llm_client import OpenAILLMClient


def test_llm_client_defaults_to_dotenv_settings(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=env-api-key",
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_BASE_MODEL=env-base-model",
                "OPENAI_TIMEOUT_SECONDS=12.5",
            ]
        ),
        encoding="utf-8",
    )
    prompt_file = tmp_path / "prompt.json"
    prompt_file.write_text('{"simple": {"zh": "hello"}}', encoding="utf-8")
    recorded = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            recorded.update(kwargs)

    monkeypatch.setattr("agent.llm.llm_client.AsyncOpenAI", FakeAsyncOpenAI)

    client = OpenAILLMClient(env_path=env_path, prompt_file=prompt_file)
    payload = client._build_chat_payload(
        model=None,
        temperature=None,
        max_tokens=None,
        timeout=None,
        response_format=None,
        messages=[{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert recorded == {
        "api_key": "env-api-key",
        "base_url": "https://llm.example.test/v1",
        "timeout": 12.5,
    }
    assert payload["model"] == "env-base-model"


def test_explicit_llm_client_arguments_override_dotenv(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=env-api-key",
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_BASE_MODEL=env-base-model",
            ]
        ),
        encoding="utf-8",
    )
    prompt_file = tmp_path / "prompt.json"
    prompt_file.write_text('{"simple": {"zh": "hello"}}', encoding="utf-8")
    recorded = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            recorded.update(kwargs)

    monkeypatch.setattr("agent.llm.llm_client.AsyncOpenAI", FakeAsyncOpenAI)

    client = OpenAILLMClient(
        env_path=Path(env_path),
        prompt_file=prompt_file,
        api_key="explicit-key",
        base_url="https://explicit.example.test/v1",
        default_model="explicit-model",
        timeout=3,
    )
    payload = client._build_chat_payload(
        model=None,
        temperature=None,
        max_tokens=None,
        timeout=None,
        response_format=None,
        messages=[{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert recorded == {
        "api_key": "explicit-key",
        "base_url": "https://explicit.example.test/v1",
        "timeout": 3,
    }
    assert payload["model"] == "explicit-model"
