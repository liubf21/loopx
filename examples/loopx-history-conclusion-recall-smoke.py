#!/usr/bin/env python3
"""Focused smoke for LoopX history-conclusion export + resources-scope recall.

Public-safe and offline: it does not require a live OpenViking backend, network,
credentials, or raw transcripts. It pins the durable end-to-end boundary
behaviors, including negative cases for the review findings:

1. Export drops any conclusion field carrying a local path or secret-like token.
2. Runs with no substantive conclusion beyond classification are skipped.
3. render/export reject an unsafe goal_id (path traversal) and never echo an
   unsafe generated_at into the document.
4. export retires the prior generation, so stale conclusions do not survive an
   empty later history; and it never exposes the local path in the public
   projection.
5. The resources-scope recall helper validates its query/scope/limit contract
   and sanitizes provider-produced summaries (drop-on-hit).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loopx.extensions.openviking_semantic_preference import history_export  # noqa: E402
from loopx.extensions.openviking_semantic_preference.history_export import (  # noqa: E402
    HISTORY_EXPORT_SCHEMA_VERSION,
    HISTORY_RECALL_SCHEMA_VERSION,
    conclusion_fields,
    export_goal_conclusions,
    recall_history_conclusions,
    render_conclusion_markdown,
)


def _expect_value_error(fn, message: str) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(message)


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
    texts = [text for _, text in conclusion_fields(run)]
    assert any("residual model" in t for t in texts)
    assert not any("/Users/" in t for t in texts), "local path leaked"
    assert not any("ghp_" in t for t in texts), "secret token leaked"


def test_noise_run_is_skipped() -> None:
    assert render_conclusion_markdown("goal-x", {"classification": "quota_slot_spent"}) is None
    md = render_conclusion_markdown(
        "goal-x", {"classification": "did_something", "recommended_action": "do the next thing"}
    )
    assert md is not None and "do the next thing" in md


def test_render_rejects_unsafe_goal_id() -> None:
    substantive = {"classification": "c", "recommended_action": "do it"}
    for bad in ("../escaped", "a/b", "..", "."):
        _expect_value_error(
            lambda: render_conclusion_markdown(bad, substantive),
            f"unsafe goal_id must raise: {bad!r}",
        )


def test_unsafe_generated_at_is_not_echoed() -> None:
    md = render_conclusion_markdown(
        "goal-x",
        {
            "classification": "c",
            "recommended_action": "do it",
            "generated_at": "/Users/attacker/`ls`",
        },
    )
    assert md is not None
    assert "/Users/" not in md, "unsafe generated_at leaked into document"
    assert "generated_at: ``" in md, "unsafe timestamp should be dropped to empty"


def test_export_rejects_unsafe_goal_id(tmp_path: Path) -> None:
    _expect_value_error(
        lambda: export_goal_conclusions(
            goal_id="../escaped",
            registry_path=tmp_path / "registry.json",
            runtime_root=tmp_path,
            out_dir=tmp_path / "out",
        ),
        "export must reject path-traversal goal_id before touching the filesystem",
    )


def test_export_retires_prior_generation_and_hides_local_path(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out"
    goal = "retire-me"
    # seed a stale exported doc from a prior generation
    (out / goal).mkdir(parents=True)
    (out / goal / "stale.md").write_text("# stale conclusion", encoding="utf-8")

    # later history is empty
    monkeypatch.setattr(history_export, "collect_history", lambda **_: {"runs": []})
    result = export_goal_conclusions(
        goal_id=goal,
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path,
        out_dir=out,
    )
    # stale doc retired, nothing survives an empty history
    assert not (out / goal / "stale.md").exists(), "stale conclusion survived empty history"
    assert list((out / goal).glob("*.md")) == []
    proj = result["public_projection"]
    assert proj["retired_prior_generation"] == 1
    assert proj["written"] == 0
    # public projection must not expose a local filesystem path
    assert "out_dir" not in proj
    assert "/" not in "".join(str(v) for v in proj.values() if isinstance(v, str) and v != proj["target_scope_hint"])
    # local path is only in the local receipt
    assert result["local_receipt"]["out_dir"].endswith(f"out/{goal}")


def test_recall_input_contract() -> None:
    for bad in ("", " "):
        _expect_value_error(
            lambda: recall_history_conclusions(query=bad, scope_uri="viking://user/x/resources/h"),
            "empty query must raise",
        )
    _expect_value_error(
        lambda: recall_history_conclusions(query="q", scope_uri="/local/path"),
        "non-viking scope must raise",
    )
    _expect_value_error(
        lambda: recall_history_conclusions(query="q", scope_uri="viking://user/x/resources/h", limit=99),
        "out-of-range limit must raise",
    )


def test_recall_sanitizes_provider_summaries(monkeypatch) -> None:
    scope = "viking://user/x/resources/h"

    class _Completed:
        returncode = 0
        stdout = (
            '{"result": {"resources": ['
            f'{{"uri": "{scope}/a.md", "score": 0.9, "abstract": "safe conclusion about storage"}},'
            f'{{"uri": "{scope}/b.md", "score": 0.8, "abstract": "leaked /Users/secret/report.md"}},'
            '{"uri": "viking://user/x/peers/other/memories/z", "score": 0.7, "abstract": "out of scope"}'
            "]}}"
        )

    monkeypatch.setattr(history_export.subprocess, "run", lambda *a, **k: _Completed())
    out = recall_history_conclusions(query="storage", scope_uri=scope, ov_bin="ov")
    summaries = [i["summary"] for i in out["items"]]
    uris = [i["uri"] for i in out["items"]]
    assert any("safe conclusion" in s for s in summaries)
    assert not any("/Users/" in s for s in summaries), "unsafe provider summary leaked"
    assert all(u.startswith(scope + "/") for u in uris), "out-of-scope uri returned"
    assert out["dropped_unsafe"] >= 1


def test_schema_versions_are_stable() -> None:
    assert HISTORY_EXPORT_SCHEMA_VERSION == "loopx_history_conclusion_export_v0"
    assert HISTORY_RECALL_SCHEMA_VERSION == "loopx_history_conclusion_recall_v0"


def main() -> int:
    import tempfile

    class _MonkeyPatch:
        def __init__(self) -> None:
            self._undo = []

        def setattr(self, target, name, value=None):
            if value is None:  # setattr(obj_attr_path, value) form unused here
                raise NotImplementedError
            old = getattr(target, name)
            self._undo.append((target, name, old))
            setattr(target, name, value)

        def undo(self):
            for target, name, old in reversed(self._undo):
                setattr(target, name, old)

    test_export_drops_local_paths_and_secrets()
    test_noise_run_is_skipped()
    test_render_rejects_unsafe_goal_id()
    test_unsafe_generated_at_is_not_echoed()
    test_recall_input_contract()
    test_schema_versions_are_stable()

    with tempfile.TemporaryDirectory() as d:
        test_export_rejects_unsafe_goal_id(Path(d))
    with tempfile.TemporaryDirectory() as d:
        mp = _MonkeyPatch()
        try:
            test_export_retires_prior_generation_and_hides_local_path(Path(d), mp)
        finally:
            mp.undo()
    mp = _MonkeyPatch()
    try:
        test_recall_sanitizes_provider_summaries(mp)
    finally:
        mp.undo()

    print("ok: loopx-history-conclusion-recall smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
