"""Standalone monthly cost estimator — no API calls, just the math.

    python -m src.costs
"""
from __future__ import annotations

from pathlib import Path
import yaml

MIN_PER_MONTH = 60 * 24 * 30  # 43,200


def estimate(config: dict) -> dict:
    m = config["models"]
    g = config["generation"]

    # Performers: one call per segment, each ~context_tokens in + spoken out.
    seg_min = g["segment_minutes"]
    calls = MIN_PER_MONTH / seg_min
    out_per_call = seg_min * g["words_per_minute"] * 1.33  # words -> tokens
    in_per_call = g["context_tokens"]

    perf = m["performer"]
    perf_in = calls * in_per_call
    perf_out = calls * out_per_call
    perf_usd = perf_in / 1e6 * perf["price_in"] + perf_out / 1e6 * perf["price_out"]

    # Writer: ~once per show. 8 shows/day * 30 = 240; round to 300 for weekly extras.
    wr = m["writer"]
    wr_runs = 300
    wr_in, wr_out = 3000, wr["max_tokens"]
    wr_usd = (wr_runs * wr_in) / 1e6 * wr["price_in"] + \
             (wr_runs * wr_out) / 1e6 * wr["price_out"]

    return {
        "performer_model": perf["id"],
        "writer_model": wr["id"],
        "performer_usd": perf_usd,
        "writer_usd": wr_usd,
        "total_usd": perf_usd + wr_usd,
    }


def main():
    config = yaml.safe_load(Path("config.yaml").read_text())
    e = estimate(config)
    print("KAOS-FM — estimated monthly LLM cost\n")
    print(f"  performers  {e['performer_model']:<45} ${e['performer_usd']:.2f}")
    print(f"  head writer {e['writer_model']:<45} ${e['writer_usd']:.2f}")
    print(f"  {'-'*62}")
    print(f"  LLM total{'':<48}${e['total_usd']:.2f}/mo")
    print("  + Kokoro TTS (self-hosted): $0   + server: your Netcup box")


if __name__ == "__main__":
    main()
