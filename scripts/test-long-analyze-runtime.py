#!/usr/bin/env python3
"""Stable entry point for the single-state long-analysis runtime tests."""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).with_name("test-long-analyze-runtime-refactor.py")),
        run_name="__main__",
    )
