"""Thin OpenRouter chat client + a running cost meter."""
from __future__ import annotations

import os
import time
import requests

_API = "https://openrouter.ai/api/v1/chat/completions"


class CostMeter:
    """Accumulates token usage and dollar cost across a run."""

    def __init__(self):
        self.in_tokens = 0
        self.out_tokens = 0
        self.usd = 0.0

    def add(self, usage: dict, price_in: float, price_out: float):
        pi = usage.get("prompt_tokens", 0)
        po = usage.get("completion_tokens", 0)
        self.in_tokens += pi
        self.out_tokens += po
        self.usd += pi / 1e6 * price_in + po / 1e6 * price_out

    def summary(self) -> str:
        return (f"{self.in_tokens:,} in + {self.out_tokens:,} out "
                f"= ${self.usd:.4f}")


METER = CostMeter()


def chat(model_cfg: dict, messages: list[dict], retries: int = 3) -> str:
    """Call an OpenRouter model. `model_cfg` is a config.yaml models.* block."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set (see .env.example)")

    headers = {
        "Authorization": f"Bearer {key}",
        "X-Title": os.environ.get("OPENROUTER_APP_NAME", "The Frequency"),
    }
    if url := os.environ.get("OPENROUTER_APP_URL"):
        headers["HTTP-Referer"] = url

    payload = {
        "model": model_cfg["id"],
        "messages": messages,
        "temperature": model_cfg.get("temperature", 1.0),
        "max_tokens": model_cfg.get("max_tokens", 1200),
    }
    for k in ("frequency_penalty", "presence_penalty", "repetition_penalty"):
        if k in model_cfg:
            payload[k] = model_cfg[k]

    last = None
    for attempt in range(retries):
        try:
            r = requests.post(_API, headers=headers, json=payload, timeout=90)
            r.raise_for_status()
            data = r.json()
            METER.add(data.get("usage", {}),
                      model_cfg.get("price_in", 0.0),
                      model_cfg.get("price_out", 0.0))
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
            if not content or not content.strip():
                raise ValueError("empty completion")  # provider glitch: retry
            return content.strip()
        except Exception as e:  # noqa: BLE001 — retry any transient failure
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"OpenRouter call failed after {retries} tries: {last}")
