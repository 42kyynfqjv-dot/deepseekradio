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

    # Performers: one call per PART (lines_per_beat lines ≈ 2 min of air each).
    lines_per_part = g.get("lines_per_beat", 22)
    min_per_part = lines_per_part * 12 / g["words_per_minute"]  # ~12 words/line
    calls = MIN_PER_MONTH / max(min_per_part, 0.5)
    out_per_call = lines_per_part * 16  # tokens per line incl. JSON overhead
    in_per_call = g["context_tokens"]

    perf = m["performer"]
    perf_in = calls * in_per_call
    perf_out = calls * out_per_call
    perf_usd = perf_in / 1e6 * perf["price_in"] + perf_out / 1e6 * perf["price_out"]

    # Script doctor: one cheap call per part, in ≈ the lines twice + rules.
    pol_usd = 0.0
    if "polish" in m:
        pol = m["polish"]
        pol_usd = (calls * (out_per_call + 700)) / 1e6 * pol["price_in"] +                   (calls * out_per_call) / 1e6 * pol["price_out"]

    # Writer: ~once per show. 8 shows/day * 30 = 240; round to 300 for weekly extras.
    wr = m["writer"]
    wr_runs = 300
    wr_in, wr_out = 3000, wr["max_tokens"]
    wr_usd = (wr_runs * wr_in) / 1e6 * wr["price_in"] + \
             (wr_runs * wr_out) / 1e6 * wr["price_out"]

    # Hourly Frequency News: one small writer call per hour.
    news_usd = 0.0
    if config.get("news", {}).get("enabled"):
        runs = 24 * 30
        news_usd = (runs * 1200) / 1e6 * wr["price_in"] + \
                   (runs * 300) / 1e6 * wr["price_out"]

    return {
        "performer_model": perf["id"],
        "writer_model": wr["id"],
        "performer_usd": perf_usd,
        "writer_usd": wr_usd,
        "news_usd": news_usd,
        "polish_usd": pol_usd,
        "total_usd": perf_usd + wr_usd + news_usd + pol_usd,
    }


def main():
    config = yaml.safe_load(Path("config.yaml").read_text())
    e = estimate(config)
    print("The Frequency — estimated monthly LLM cost\n")
    print(f"  performers  {e['performer_model']:<45} ${e['performer_usd']:.2f}")
    print(f"  head writer {e['writer_model']:<45} ${e['writer_usd']:.2f}")
    if e["news_usd"]:
        print(f"  hourly news {e['writer_model']:<45} ${e['news_usd']:.2f}")
    if e.get("polish_usd"):
        print(f"  script dr.  {config['models']['polish']['id']:<45} ${e['polish_usd']:.2f}")
    print(f"  {'-'*62}")
    print(f"  LLM total{'':<48}${e['total_usd']:.2f}/mo")
    print("  + Kokoro TTS (self-hosted): $0   + server: your Netcup box")


if __name__ == "__main__":
    main()
