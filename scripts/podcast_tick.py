"""One podcast pipeline pass: harvest aired segments, cut quiet episodes,
encode, upload, rewrite feeds. Runs from frequency-podcast.timer as kaos,
WorkingDirectory=/opt/kaos/app. Everything inside is best-effort — a bad
tick must never matter to the air."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import podcast  # noqa: E402

if __name__ == "__main__":
    try:
        podcast.main()
    except Exception as e:
        print(f"  !! podcast tick failed: {e}")
        sys.exit(0)
