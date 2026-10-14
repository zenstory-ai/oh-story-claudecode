"""Run rankmin without relying on the process working directory."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    bridge = Path(__file__).resolve().parent
    bridge_text = str(bridge)
    if bridge_text not in sys.path:
        sys.path.insert(0, bridge_text)
    from rankmin.__main__ import main as rank_main

    return rank_main()


if __name__ == "__main__":
    raise SystemExit(main())
