from __future__ import annotations

import json
from typing import Any

from utils.ollama_client import OllamaClient, OllamaConfig, OllamaError


AI_ENABLED_KEY = "ai/ollama_enabled"
AI_BASE_URL_KEY = "ai/ollama_base_url"
AI_MODEL_KEY = "ai/ollama_model"
AI_TEMPERATURE_KEY = "ai/ollama_temperature"
AI_TIMEOUT_S_KEY = "ai/ollama_timeout_s"


def is_ai_enabled(settings) -> bool:
    try:
        return bool(settings.value(AI_ENABLED_KEY, False, bool))
    except Exception:
        # QSettings bool conversion can be inconsistent across Qt/PyQt versions
        v = str(settings.value(AI_ENABLED_KEY, "false"))
        return v.strip().lower() in {"1", "true", "yes", "on"}


def get_ollama_client(settings) -> OllamaClient:
    base_url = str(settings.value(AI_BASE_URL_KEY, "http://localhost:11434", str) or "").strip()
    model = str(settings.value(AI_MODEL_KEY, "llama3.1", str) or "").strip() or "llama3.1"
    try:
        temperature = float(settings.value(AI_TEMPERATURE_KEY, 0.3, float))
    except Exception:
        temperature = float(settings.value(AI_TEMPERATURE_KEY, 0.3))
    try:
        timeout_s = float(settings.value(AI_TIMEOUT_S_KEY, 60.0, float))
    except Exception:
        timeout_s = float(settings.value(AI_TIMEOUT_S_KEY, 60.0))

    cfg = OllamaConfig(
        base_url=base_url,
        model=model,
        temperature=max(0.0, min(2.0, float(temperature))),
        timeout_s=max(5.0, min(600.0, float(timeout_s))),
    )
    return OllamaClient(cfg)


def model_is_available(settings) -> tuple[bool, str]:
    """
    Returns (ok, message). Uses Ollama tags list to verify model name exists locally.
    """
    try:
        client = get_ollama_client(settings)
        models = client.list_models()
        want = str(settings.value(AI_MODEL_KEY, "llama3.1", str) or "").strip() or "llama3.1"
        if not models:
            return False, "No models found in Ollama."
        if want in models:
            return True, ""
        # Allow match by prefix before digest/variant.
        alt = [m for m in models if m.split(":")[0] == want.split(":")[0]]
        if alt:
            return False, f"Model '{want}' not found. Available similar: {', '.join(alt[:6])}"
        return False, f"Model '{want}' not found in Ollama. Install it with: ollama pull {want}"
    except Exception as e:
        return False, str(e)


def parse_strict_json(text: str) -> dict[str, Any]:
    s = (text or "").strip()
    # Allow models that wrap JSON with markdown fences.
    if s.startswith("```"):
        s = s.strip("`").strip()
        # Try to drop leading language tag
        if "\n" in s and s.split("\n", 1)[0].strip().lower() in {"json", "javascript"}:
            s = s.split("\n", 1)[1].strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        # Many models wrap JSON with prose. Try extracting the first {...} block.
        try:
            start = s.find("{")
            end = s.rfind("}")
            if start >= 0 and end > start:
                obj = json.loads(s[start : end + 1])
                return obj if isinstance(obj, dict) else {}
        except Exception:
            pass
        return {}


__all__ = [
    "OllamaError",
    "AI_ENABLED_KEY",
    "AI_BASE_URL_KEY",
    "AI_MODEL_KEY",
    "AI_TEMPERATURE_KEY",
    "AI_TIMEOUT_S_KEY",
    "is_ai_enabled",
    "get_ollama_client",
    "parse_strict_json",
    "model_is_available",
]

