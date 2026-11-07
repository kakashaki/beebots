"""OpenEvolve fitness for the long-horizon research loop. Research only.

Selection uses train (2021-2023) and validation (2024-01-01..2025-06-30) only.
Bars at or after 2025-07-01 UTC are holdout and are not scored, returned, or written.
This module does not start an LLM call. A missing train window returns score 0.
Children, if a future batch writes them, go under research_out/candidates and never
replace fixtures or the promoted runtime programs.
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hist_eval import HOLDOUT_START, load_csv

def evaluate(program_path):
    path = os.environ.get("HIST_BARS", "")
    if not path or not os.path.exists(path):
        return {"combined_score": 0.0, "evolution_running": 0.0, "error": "awaiting_dataset"}
    bars = load_csv(path)
    holdout = sum(1 for b in bars if b["t"] >= HOLDOUT_START)
    selectable = [b for b in bars if b["t"] < HOLDOUT_START]
    if not selectable:
        return {
            "combined_score": 0.0,
            "evolution_running": 0.0,
            "error": "train_validation_absent",
            "holdout_bars_ignored": holdout,
            "holdout_scored": 0.0,
        }
    # Real train/validation scoring is intentionally not implied by a holdout-only file.
    # A later batch may score `selectable` only. It must not read the holdout slice.
    return {
        "combined_score": 0.0,
        "evolution_running": 0.0,
        "error": "selection_not_started",
        "selectable_bars": len(selectable),
        "holdout_bars_ignored": holdout,
        "holdout_scored": 0.0,
        "program": os.path.basename(program_path),
    }
