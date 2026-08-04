#!/usr/bin/env python3
"""Focused smoke for LoopX history-conclusion export + resources-scope recall.

Public-safe and offline: it does not require a live OpenViking backend, network,
credentials, or raw transcripts. It pins the durable end-to-end boundary
behaviors, including negative cases for the review findings:

1. Export drops any conclusion field carrying a local path or secret-like token.
2. Runs with no substantive conclusion beyond classification are skipped.
3. render/export reject an unsafe goal_id (path traversal) and never echo an
   unsafe generated_at into the document.
4. Export replaces only its manifest-owned prior generation, preserves foreign
   files, publishes unique documents, and leaves the prior corpus intact if
   staging fails.
5. The resources-scope recall helper validates its query/scope/limit contract
   and sanitizes provider-produced summaries and URIs (drop-on-hit).
"""
from __future__ import annotations

import json
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


def _export_runs(
    tmp_path: Path,
    monkeypatch,
    *,
    goal_id: str,
    runs: list[dict],
) -> dict:
    monkeypatch.setattr(history_export, "collect_history", lambda **_: {"runs": runs})
    return export_goal_conclusions(
        goal_id=goal_id,
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path,
        out_dir=tmp_path / "out",
    )


def _corpus_snapshot(result: dict) -> tuple[Path, Path, bytes, dict[str, bytes]]:
    receipt = result["local_receipt"]
    goal_out = Path(receipt["out_dir"])
    manifest_path = Path(receipt["manifest_path"])
    documents = {
        name: (goal_out / name).read_bytes() for name in receipt["owned_files"]
    }
    return goal_out, manifest_path, manifest_path.read_bytes(), documents


def _assert_corpus_unchanged(
    goal_out: Path,
    manifest_path: Path,
    manifest: bytes,
    documents: dict[str, bytes],
) -> None:
    assert manifest_path.read_bytes() == manifest
    assert {name: (goal_out / name).read_bytes() for name in documents} == documents
    assert sorted(path.name for path in goal_out.glob("*.md")) == sorted(documents)


def test_export_drops_local_paths_and_secrets() -> None:
    # Build the secret at runtime so this source file contains no literal
    # credential for the repo boundary scanner, while the sanitizer still sees a
    # real secret-shaped value at test time.
    fake_secret = "token" + "=" + "ghp_" + "a" * 36
    run = {
        "classification": "example_conclusion",
        "recommended_action": "freeze the cross-market alert contract before evidence",
        "state": {
            "progress": [
                "Wrote artifact under /Users/someone/private/secret-report.md",
                f"{fake_secret} committed by mistake",
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


def test_export_preserves_foreign_files_when_retiring_owned_generation(
    tmp_path: Path, monkeypatch
) -> None:
    out = tmp_path / "out"
    goal = "retire-me"
    runs = [
        {
            "classification": "prior",
            "generated_at": "2026-08-04T01:02:03Z",
            "recommended_action": "retain only until the next generation",
        }
    ]
    first = _export_runs(tmp_path, monkeypatch, goal_id=goal, runs=runs)
    goal_out = out / goal
    owned_files = set(first["local_receipt"]["owned_files"])
    assert len(owned_files) == 1
    foreign = goal_out / "foreign.md"
    foreign.write_text("# maintained by another publisher", encoding="utf-8")

    # later history is empty
    result = _export_runs(tmp_path, monkeypatch, goal_id=goal, runs=[])
    assert foreign.exists(), "exporter deleted a foreign markdown file"
    corpus_out = Path(result["local_receipt"]["out_dir"])
    assert all(not (corpus_out / name).exists() for name in owned_files)
    assert list(goal_out.glob("*.md")) == [foreign]
    assert list(corpus_out.glob("*.md")) == []
    proj = result["public_projection"]
    assert proj["retired_prior_generation"] == len(owned_files)
    assert proj["written"] == 0
    # public projection must not expose a local filesystem path
    assert "out_dir" not in proj
    assert "/" not in "".join(str(v) for v in proj.values() if isinstance(v, str) and v != proj["target_scope_hint"])
    # local path is only in the local receipt
    assert result["local_receipt"]["out_dir"].endswith(
        f"out/{goal}/history-conclusions"
    )


def test_export_uses_unique_names_and_reports_exact_document_count(
    tmp_path: Path, monkeypatch
) -> None:
    runs = [
        {
            "classification": "same",
            "generated_at": "2026-08-04T01:02:03Z",
            "recommended_action": "first conclusion",
        },
        {
            "classification": "same",
            "generated_at": "2026-08-04T01:02:03Z",
            "recommended_action": "second conclusion",
        },
    ]
    result = _export_runs(tmp_path, monkeypatch, goal_id="collision", runs=runs)
    documents = list(Path(result["local_receipt"]["out_dir"]).glob("*.md"))
    assert len(documents) == 2, "same timestamp/classification overwrote a document"
    assert len({path.name for path in documents}) == 2
    assert result["public_projection"]["written"] == len(documents)
    assert sorted(result["local_receipt"]["owned_files"]) == sorted(
        path.name for path in documents
    )


def test_export_write_failure_preserves_prior_owned_corpus(
    tmp_path: Path, monkeypatch
) -> None:
    out = tmp_path / "out"
    goal = "atomic"
    prior_runs = [
        {
            "classification": "prior",
            "generated_at": "2026-08-04T01:02:03Z",
            "recommended_action": "published prior conclusion",
        }
    ]
    first = _export_runs(
        tmp_path,
        monkeypatch,
        goal_id=goal,
        runs=prior_runs,
    )
    goal_out, manifest_path, prior_manifest, prior_documents = _corpus_snapshot(first)

    new_runs = [
        {
            "classification": "new",
            "generated_at": "2026-08-04T04:05:06Z",
            "recommended_action": f"new conclusion {index}",
        }
        for index in range(2)
    ]
    monkeypatch.setattr(history_export, "collect_history", lambda **_: {"runs": new_runs})
    original_write_text = Path.write_text
    staged_document_writes = 0

    def _fail_second_staged_document(path: Path, data: str, **kwargs) -> int:
        nonlocal staged_document_writes
        if path.suffix == ".md" and path.parent != goal_out:
            staged_document_writes += 1
            if staged_document_writes == 2:
                raise OSError("simulated staged write failure")
        return original_write_text(path, data, **kwargs)

    monkeypatch.setattr(Path, "write_text", _fail_second_staged_document)
    try:
        export_goal_conclusions(
            goal_id=goal,
            registry_path=tmp_path / "registry.json",
            runtime_root=tmp_path,
            out_dir=out,
        )
    except OSError as exc:
        assert "simulated staged write failure" in str(exc)
    else:
        raise AssertionError("staged write failure must propagate")

    _assert_corpus_unchanged(
        goal_out, manifest_path, prior_manifest, prior_documents
    )


def test_export_publish_failure_rolls_back_prior_owned_corpus(
    tmp_path: Path, monkeypatch
) -> None:
    out = tmp_path / "out"
    goal = "rollback"
    first = _export_runs(
        tmp_path,
        monkeypatch,
        goal_id=goal,
        runs=[
            {
                "classification": "prior",
                "generated_at": "2026-08-04T01:02:03Z",
                "recommended_action": "published prior conclusion",
            }
        ],
    )
    goal_out, manifest_path, prior_manifest, prior_documents = _corpus_snapshot(first)

    monkeypatch.setattr(
        history_export,
        "collect_history",
        lambda **_: {
            "runs": [
                {
                    "classification": "new",
                    "generated_at": "2026-08-04T04:05:06Z",
                    "recommended_action": "replacement conclusion",
                }
            ]
        },
    )
    original_replace = history_export.os.replace
    failed = False

    def _fail_manifest_publish(source: Path, destination: Path) -> None:
        nonlocal failed
        if (
            not failed
            and Path(source).name == "publish"
            and Path(destination) == goal_out
        ):
            failed = True
            raise OSError("simulated corpus publish failure")
        original_replace(source, destination)

    monkeypatch.setattr(history_export.os, "replace", _fail_manifest_publish)
    try:
        export_goal_conclusions(
            goal_id=goal,
            registry_path=tmp_path / "registry.json",
            runtime_root=tmp_path,
            out_dir=out,
        )
    except OSError as exc:
        assert "simulated corpus publish failure" in str(exc)
    else:
        raise AssertionError("publication failure must propagate after rollback")

    assert failed
    _assert_corpus_unchanged(
        goal_out, manifest_path, prior_manifest, prior_documents
    )


def test_recall_input_contract() -> None:
    for bad in ("", " "):
        _expect_value_error(
            lambda: recall_history_conclusions(query=bad, scope_uri="viking://user/x/resources/h"),
            "empty query must raise",
        )
    fake_secret = "token" + "=" + "ghp_" + "a" * 36
    for bad in ("/Users/private/query.txt", fake_secret):
        _expect_value_error(
            lambda bad=bad: recall_history_conclusions(
                query=bad, scope_uri="viking://user/x/resources/h"
            ),
            "unsafe query must raise before invoking ov",
        )
    _expect_value_error(
        lambda: recall_history_conclusions(query="q", scope_uri="/local/path"),
        "non-viking scope must raise",
    )
    _expect_value_error(
        lambda: recall_history_conclusions(query="q", scope_uri="viking://user/x/resources/h", limit=99),
        "out-of-range limit must raise",
    )


def test_recall_rejects_unsafe_scope_and_drops_unsafe_returned_uris(
    monkeypatch,
) -> None:
    fake_secret = "token" + "=" + "ghp_" + "a" * 36
    unsafe_scopes = (
        "viking://user/x/resources/h//Users/private/report",
        "viking://user/x/resources/h/%252FUsers/private/report",
        "viking://user/x/resources/h/%00injected",
        "viking://user/x/resources/h\ninjected",
        f"viking://user/x/resources/h/{fake_secret}",
    )
    calls = 0

    def _must_not_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("unsafe scope must be rejected before invoking ov")

    monkeypatch.setattr(history_export.subprocess, "run", _must_not_run)
    for scope in unsafe_scopes:
        _expect_value_error(
            lambda scope=scope: recall_history_conclusions(
                query="storage", scope_uri=scope, ov_bin="ov"
            ),
            f"unsafe scope must raise: {scope!r}",
        )
    assert calls == 0

    scope = "viking://user/x/resources/h"

    class _Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "result": {
                    "resources": [
                        {
                            "uri": f"{scope}/safe.md",
                            "score": 0.9,
                            "abstract": "safe conclusion",
                        },
                        {
                            "uri": f"{scope}/unsafe-score.md",
                            "score": fake_secret,
                            "abstract": "unsafe score",
                        },
                        {
                            "uri": f"{scope}//Users/private/report.md",
                            "score": 0.8,
                            "abstract": "unsafe path uri",
                        },
                        {
                            "uri": f"{scope}/%252FUsers/private/report.md",
                            "score": 0.75,
                            "abstract": "encoded unsafe path uri",
                        },
                        {
                            "uri": f"{scope}/line\nbreak.md",
                            "score": 0.7,
                            "abstract": "unsafe control uri",
                        },
                        {
                            "uri": f"{scope}/%00control.md",
                            "score": 0.65,
                            "abstract": "encoded unsafe control uri",
                        },
                        {
                            "uri": f"{scope}/{fake_secret}",
                            "score": 0.6,
                            "abstract": "unsafe secret uri",
                        },
                    ]
                }
            }
        )

    monkeypatch.setattr(history_export.subprocess, "run", lambda *a, **k: _Completed())
    result = recall_history_conclusions(
        query="storage", scope_uri=scope, ov_bin="ov"
    )
    assert [item["uri"] for item in result["items"]] == [f"{scope}/safe.md"]
    assert result["dropped_unsafe"] >= 5
    serialized = json.dumps(result)
    assert "/Users/" not in serialized
    assert fake_secret not in serialized
    assert "line\\nbreak" not in serialized


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

    with tempfile.TemporaryDirectory() as directory:
        test_export_rejects_unsafe_goal_id(Path(directory))
    for test in (
        test_export_preserves_foreign_files_when_retiring_owned_generation,
        test_export_uses_unique_names_and_reports_exact_document_count,
        test_export_write_failure_preserves_prior_owned_corpus,
        test_export_publish_failure_rolls_back_prior_owned_corpus,
    ):
        directory = tempfile.TemporaryDirectory()
        mp = _MonkeyPatch()
        try:
            test(Path(directory.name), mp)
        finally:
            mp.undo()
            directory.cleanup()
    for test in (
        test_recall_rejects_unsafe_scope_and_drops_unsafe_returned_uris,
        test_recall_sanitizes_provider_summaries,
    ):
        mp = _MonkeyPatch()
        try:
            test(mp)
        finally:
            mp.undo()

    print("ok: loopx-history-conclusion-recall smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
