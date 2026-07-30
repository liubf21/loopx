#!/usr/bin/env python3
"""Focused smoke for LoopX history-conclusion export + resources-scope recall.

Public-safe and offline: it does not require a live OpenViking backend, network,
credentials, or raw transcripts. It pins the durable behaviors:

1. Export drops any conclusion field carrying a local path or secret-like token
   (public/private boundary enforcement via public_safe_compact_text).
2. Runs with no substantive conclusion beyond classification are skipped as noise.
3. The resources-scope recall helper validates its input contract and never
   targets the peer-preference scope.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loopx.extensions.openviking_semantic_preference.history_export import (  # noqa: E402
    HISTORY_EXPORT_SCHEMA_VERSION,
    HISTORY_RECALL_SCHEMA_VERSION,
    conclusion_fields,
    recall_history_conclusions,
    render_conclusion_markdown,
)


def test_export_drops_local_paths_and_secrets() -> None:
    run = {
        "classification": "example_conclusion",
        "recommended_action": "freeze the cross-market alert contract before evidence",
        "state": {
            "progress": [
                "Wrote artifact under /Users/someone/private/secret-report.md",
                "token=ghp_abcdefghijklmnopqrstuvwxyz0123456789 committed by mistake",
                "Validated the residual model on untouched folds",
            ]
        },
    }
    labels = {label for label, _ in conclusion_fields(run)}
    texts = [text for _, text in conclusion_fields(run)]
    # substantive safe fields survive
    assert "recommended_action" in labels
    assert any("residual model" in t for t in texts)
    # local path and secret rows are dropped, not exported
    assert not any("/Users/" in t for t in texts), "local path leaked"
    assert not any("ghp_" in t for t in texts), "secret token leaked"


def test_noise_run_is_skipped() -> None:
    noise = {"classification": "quota_slot_spent"}
    assert render_conclusion_markdown("g", noise) is None
    substantive = {
        "classification": "did_something",
        "recommended_action": "do the next bounded thing",
    }
    md = render_conclusion_markdown("g", substantive)
    assert md is not None and "do the next bounded thing" in md


def test_recall_input_contract() -> None:
    # empty query rejected
    for bad in ("", " "):
        try:
            recall_history_conclusions(query=bad, scope_uri="viking://user/x/resources/h")
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("empty query must raise")
    # non-viking scope rejected (never targets peer memories by accident)
    try:
        recall_history_conclusions(query="q", scope_uri="/local/path")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("non-viking scope must raise")
    # out-of-range limit rejected
    try:
        recall_history_conclusions(
            query="q", scope_uri="viking://user/x/resources/h", limit=99
        )
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("out-of-range limit must raise")


def test_schema_versions_are_stable() -> None:
    assert HISTORY_EXPORT_SCHEMA_VERSION == "loopx_history_conclusion_export_v0"
    assert HISTORY_RECALL_SCHEMA_VERSION == "loopx_history_conclusion_recall_v0"


def main() -> int:
    test_export_drops_local_paths_and_secrets()
    test_noise_run_is_skipped()
    test_recall_input_contract()
    test_schema_versions_are_stable()
    print("ok: loopx-history-conclusion-recall smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
