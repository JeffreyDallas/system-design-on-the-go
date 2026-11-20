"""Usage accounting and transparent cost estimates for pipeline runs."""
from __future__ import annotations

import os


MODEL_RATES = {
    # USD per 1M tokens; override with *_COST_PER_MILLION env vars when rates change.
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-5.4-mini": (0.75, 4.50),
}


def _rate(model: str, kind: str) -> float | None:
    env_name = f"{model.upper().replace('-', '_')}_{kind.upper()}_COST_PER_MILLION"
    configured = os.getenv(env_name, "").strip()
    if configured:
        try:
            return float(configured)
        except ValueError:
            return None
    rates = MODEL_RATES.get(model)
    if not rates:
        return None
    return rates[0 if kind == "input" else 1]


def estimate_model_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    input_rate = _rate(model, "input")
    output_rate = _rate(model, "output")
    if input_rate is None or output_rate is None:
        return None
    return round((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000, 6)


def estimate_tts_cost(provider: str, characters: int) -> float | None:
    if provider == "local":
        return 0.0
    defaults = {"google": 16.0, "elevenlabs": 80.0}
    configured = os.getenv(f"{provider.upper()}_TTS_COST_PER_MILLION_CHARS", "").strip()
    try:
        rate = float(configured) if configured else defaults.get(provider)
    except ValueError:
        rate = None
    return None if rate is None else round(characters * rate / 1_000_000, 6)
