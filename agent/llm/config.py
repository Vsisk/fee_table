from dataclasses import dataclass
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class OpenAISettings:
    enabled: bool
    api_key: str
    base_url: str | None
    base_model: str
    vl_model: str
    timeout_seconds: float

    @property
    def is_usable(self) -> bool:
        return self.enabled and bool(self.api_key.strip()) and not self.api_key.strip().startswith("<")

    @property
    def model(self) -> str:
        return self.base_model

    def model_for(self, llm_name: str) -> str:
        if llm_name == "base":
            return self.base_model
        if llm_name == "vl":
            return self.vl_model
        raise ValueError(f"Unsupported llm_name: {llm_name}")


def load_openai_settings(env_path: str | Path | None = None) -> OpenAISettings:
    values = _load_env_values(Path(env_path) if env_path else None)
    base_model = values.get("OPENAI_BASE_MODEL") or values.get("OPENAI_MODEL", "qwen3.5-35b-a3b")
    return OpenAISettings(
        enabled=_as_bool(values.get("ENABLE_LLM", values.get("ENABLE_LLM_RESOURCE_FILTER", "true"))),
        api_key=values.get("OPENAI_API_KEY", "").strip(),
        base_url=values.get("OPENAI_BASE_URL", "").strip() or None,
        base_model=base_model,
        vl_model=values.get("OPENAI_VL_MODEL", base_model),
        timeout_seconds=_as_float(values.get("OPENAI_TIMEOUT_SECONDS"), default=30.0),
    )


def _load_env_values(env_path: Path | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    paths = [env_path] if env_path else [PROJECT_ROOT / ".env", PROJECT_ROOT / "agent" / ".env"]
    for path in paths:
        if path is not None:
            values.update(_read_env_file(path))

    for key in (
        "ENABLE_LLM",
        "ENABLE_LLM_RESOURCE_FILTER",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_BASE_MODEL",
        "OPENAI_VL_MODEL",
        "OPENAI_TIMEOUT_SECONDS",
    ):
        env_value = os.environ.get(key)
        if env_value is not None:
            values[key] = env_value.strip()
    return values


def _read_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _as_bool(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default
