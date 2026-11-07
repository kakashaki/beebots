"""OpenEvolve fitness for the long-horizon research loop. Research only.

New research may use train (2021-2023) and validation (2024-01-01..2025-06-30) only.
Bars at or after 2025-07-01 UTC are withheld from that selection. They are not scored,
returned, or written. This is not a claim that the current parents have an unseen
holdout: those parents were selected through 2026-11-04, so a 2026 file is tainted
for them. This module does not start an LLM call. A missing train window returns score 0.
Children, if a future batch writes them, go under research_out/candidates and never
replace fixtures or the promoted runtime programs.
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hist_eval import HOLDOUT_START, load_csv

def _provenance(extra):
    return {
        "combined_score": 0.0,
        "evolution_running": 0.0,
        "holdout_scored": 0.0,
        "new_research_withheld_from": "2025-07-01",
        "current_parents_pristine_holdout": False,
        "parent_baseline": "tainted",
        **extra,
    }

def evaluate(program_path):
    path = os.environ.get("HIST_BARS", "")
    if not path or not os.path.exists(path):
        return _provenance({"error": "awaiting_dataset"})
    bars = load_csv(path)
    holdout = sum(1 for b in bars if b["t"] >= HOLDOUT_START)
    selectable = [b for b in bars if b["t"] < HOLDOUT_START]
    if not selectable:
        return _provenance({
            "error": "train_validation_absent",
            "holdout_bars_ignored": holdout,
        })
    # Real train/validation scoring is intentionally not implied by a holdout-only file.
    # A later batch may score `selectable` only. It must not read the holdout slice.
    return _provenance({
        "error": "selection_not_started",
        "selectable_bars": len(selectable),
        "holdout_bars_ignored": holdout,
        "program": os.path.basename(program_path),
    })
