"""Export sanitized LoopX run conclusions as public-safe documents.

This is a delivery-unit helper co-located with the OpenViking semantic-preference
provider family. It converts LoopX run-history conclusions into compact,
public-safe markdown documents suitable for ingest into an OpenViking
``resources`` scope, where they can later be recalled semantically.

Design boundary: run conclusions are *documents/knowledge*, not provider-managed
*peer preference memory*. They therefore target the ``resources`` scope and the
generic ``ov find`` document-recall path, never the peer-preference contract in
``project_peer.py``. This keeps the OpenViking ``memories`` (managed) vs
``resources`` (documents) scope convention intact.

Reuses:
- ``loopx.history.collect_history`` to read run records (no bespoke JSON parsing).
- ``loopx.control_plane.runtime.public_safety.public_safe_compact_text`` to drop
  any field carrying local paths or secret-like tokens before it leaves the repo.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from ...control_plane.runtime.public_safety import public_safe_compact_text
from ...history import collect_history, validate_goal_id_path_segment

HISTORY_EXPORT_SCHEMA_VERSION = "loopx_history_conclusion_export_v0"
HISTORY_RECALL_SCHEMA_VERSION = "loopx_history_conclusion_recall_v0"

_CONCLUSION_LIMIT = 400
_MAX_PROGRESS_BULLETS = 3
_CORPUS_DIR = "history-conclusions"
_MANIFEST_FILE = ".loopx-history-conclusion-export.json"
_MANIFEST_SCHEMA_VERSION = "loopx_history_conclusion_export_manifest_v0"
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
# Bounded ISO-8601-ish timestamp: digits, T/space, colon, dot, +/- and Z only.
_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:.+\-]{1,20}Z?$")
_MAX_URI_LENGTH = 1_000


def _safe_generated_at(value: Any) -> str:
    """Return a bounded timestamp string, or empty string if not safe.

    Never trust the raw run field as content: only echo it when it matches a
    tight timestamp shape, otherwise drop it entirely.
    """
    text = str(value or "").strip()
    if text and _TIMESTAMP_RE.match(text):
        return text
    return ""


def _slug(value: str) -> str:
    slug = _SLUG_RE.sub("-", value).strip("-")
    return slug[:80] or "run"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _document_name(
    run: Mapping[str, Any],
    markdown: str,
    *,
    digest_occurrences: dict[str, int],
) -> str:
    digest = _sha256(markdown.encode("utf-8"))
    occurrence = digest_occurrences.get(digest, 0) + 1
    digest_occurrences[digest] = occurrence
    generated_at = _safe_generated_at(run.get("generated_at"))
    classification = public_safe_compact_text(
        run.get("classification"), limit=80
    ) or "run"
    prefix = _slug(f"{generated_at}-{classification}")[:56]
    duplicate_suffix = f"-{occurrence}" if occurrence > 1 else ""
    return f"{prefix}-{digest[:16]}{duplicate_suffix}.md"


def _manifest_payload(
    *,
    goal_id: str,
    documents: Mapping[str, bytes],
) -> dict[str, Any]:
    return {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "goal_id": goal_id,
        "files": [
            {"name": name, "sha256": _sha256(data)}
            for name, data in sorted(documents.items())
        ],
    }


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_owned_manifest(path: Path, *, goal_id: str) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("history export manifest is unreadable") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("history export manifest must be an object")
    if payload.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
        raise RuntimeError("history export manifest schema is unsupported")
    if payload.get("goal_id") != goal_id:
        raise RuntimeError("history export manifest goal does not match output")
    files = payload.get("files")
    if not isinstance(files, list):
        raise RuntimeError("history export manifest files must be a list")

    owned: dict[str, str] = {}
    for item in files:
        if not isinstance(item, Mapping):
            raise RuntimeError("history export manifest file entry must be an object")
        name = str(item.get("name") or "")
        digest = str(item.get("sha256") or "")
        if (
            not name
            or Path(name).name != name
            or not name.endswith(".md")
            or not _SHA256_RE.fullmatch(digest)
            or name in owned
        ):
            raise RuntimeError("history export manifest contains an invalid file entry")
        owned[name] = digest
    return owned


def _validate_staged_generation(
    staged: Path,
    *,
    documents: Mapping[str, bytes],
    manifest: Mapping[str, Any],
) -> None:
    for name, expected in documents.items():
        if (staged / name).read_bytes() != expected:
            raise RuntimeError(f"staged history document failed readback: {name}")
    staged_manifest = json.loads((staged / _MANIFEST_FILE).read_text(encoding="utf-8"))
    if staged_manifest != manifest:
        raise RuntimeError("staged history export manifest failed readback")


def _publish_generation(
    *,
    corpus_out: Path,
    documents: Mapping[str, bytes],
    manifest: Mapping[str, Any],
) -> int:
    corpus_out.parent.mkdir(parents=True, exist_ok=True)
    if corpus_out.exists() and not (corpus_out / _MANIFEST_FILE).is_file():
        raise RuntimeError(
            "existing history corpus lacks an exporter ownership manifest"
        )
    prior_owned = _read_owned_manifest(
        corpus_out / _MANIFEST_FILE,
        goal_id=str(manifest["goal_id"]),
    )
    backup = corpus_out.parent / f".{corpus_out.name}.loopx-backup"
    if backup.exists():
        raise RuntimeError(f"stale history export backup requires inspection: {backup}")

    with tempfile.TemporaryDirectory(
        prefix=f".{corpus_out.name}.loopx-stage-",
        dir=corpus_out.parent,
    ) as temp_dir:
        staged = Path(temp_dir) / "publish"
        staged.mkdir()
        for name, data in sorted(documents.items()):
            (staged / name).write_text(data.decode("utf-8"), encoding="utf-8")
        _write_manifest(staged / _MANIFEST_FILE, manifest)
        _validate_staged_generation(
            staged,
            documents=documents,
            manifest=manifest,
        )

        had_output = corpus_out.exists()
        if had_output:
            os.replace(corpus_out, backup)
        try:
            os.replace(staged, corpus_out)
        except Exception:
            if had_output and backup.exists() and not corpus_out.exists():
                os.replace(backup, corpus_out)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    return len(prior_owned)


def _safe_viking_resource_uri(value: Any) -> str:
    def _contains_control(text: str) -> bool:
        return any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in text
        )

    uri = str(value or "").strip()
    if not uri or len(uri) > _MAX_URI_LENGTH:
        raise ValueError("viking resource uri must contain 1 to 1000 characters")
    if _contains_control(uri):
        raise ValueError("viking resource uri must not contain whitespace or controls")
    decoded = uri
    for _ in range(3):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    if unquote(decoded) != decoded:
        raise ValueError("viking resource uri is excessively encoded")
    for candidate in (uri, decoded):
        if _contains_control(candidate):
            raise ValueError("viking resource uri must not contain whitespace or controls")
        if public_safe_compact_text(candidate, limit=_MAX_URI_LENGTH) != candidate:
            raise ValueError("viking resource uri contains an unsafe surface")
        if "\\" in candidate:
            raise ValueError("viking resource uri must not contain backslashes")

    parsed = urlsplit(decoded)
    if (
        parsed.scheme != "viking"
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("scope_uri must be a structured viking:// resource uri")
    decoded_path = parsed.path
    path_segments = decoded_path.split("/")
    if (
        not decoded_path.startswith("/")
        or any(segment in {"", ".", ".."} for segment in path_segments[1:])
        or "resources" not in path_segments[1:]
    ):
        raise ValueError("scope_uri must identify a bounded resources path")
    return uri


def _is_descendant_resource_uri(uri: str, *, scope_uri: str) -> bool:
    candidate = urlsplit(uri)
    scope = urlsplit(scope_uri)
    if candidate.scheme != scope.scheme or candidate.netloc != scope.netloc:
        return False
    candidate_segments = unquote(candidate.path).split("/")[1:]
    scope_segments = unquote(scope.path).split("/")[1:]
    return (
        len(candidate_segments) > len(scope_segments)
        and candidate_segments[: len(scope_segments)] == scope_segments
    )


def _safe_score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    score = float(value)
    return score if math.isfinite(score) else None


def conclusion_fields(run: dict[str, Any]) -> list[tuple[str, str]]:
    """Return public-safe (label, text) conclusion pairs for one run.

    Every value is passed through ``public_safe_compact_text`` so any row with a
    local path or secret-like token is dropped rather than exported.
    """
    fields: list[tuple[str, str]] = []

    def _add(label: str, raw: Any) -> None:
        if not raw:
            return
        safe = public_safe_compact_text(raw, limit=_CONCLUSION_LIMIT)
        if safe:
            fields.append((label, safe))

    _add("classification", run.get("classification"))
    _add("recommended_action", run.get("recommended_action"))
    _add("delivery_outcome", run.get("delivery_outcome"))

    vision_patch = (run.get("agent_vision") or {}).get("vision_patch") or {}
    _add("last_patch_summary", vision_patch.get("last_patch_summary"))
    _add("vision_summary", vision_patch.get("vision_summary"))

    progress = (run.get("state") or {}).get("progress") or []
    for bullet in progress[-_MAX_PROGRESS_BULLETS:]:
        _add("progress", bullet)

    return fields


def render_conclusion_markdown(goal_id: str, run: dict[str, Any]) -> str | None:
    """Render one run's conclusions as public-safe markdown, or None if noise.

    A run with no substantive conclusion beyond its classification (for example a
    bare ``quota_slot_spent`` slot) is treated as noise and skipped. ``goal_id``
    is validated against the canonical single-path-segment contract and
    ``generated_at`` is echoed only when it matches a bounded timestamp shape, so
    neither can inject unsafe content into the document.
    """
    safe_goal_id = validate_goal_id_path_segment(goal_id)
    fields = conclusion_fields(run)
    substantive = [pair for pair in fields if pair[0] != "classification"]
    if not substantive:
        return None

    generated_at = _safe_generated_at(run.get("generated_at"))
    lines = [
        "# LoopX run conclusion",
        "",
        f"- goal: `{safe_goal_id}`",
        f"- generated_at: `{generated_at}`",
        "",
    ]
    for label, text in fields:
        lines.extend([f"## {label}", text, ""])
    return "\n".join(lines)


def export_goal_conclusions(
    *,
    goal_id: str,
    registry_path: Path,
    runtime_root: Path,
    out_dir: Path,
    limit: int = 50,
) -> dict[str, Any]:
    """Export the most recent ``limit`` run conclusions for one goal.

    Writes one public-safe markdown per substantive run under the exporter-owned
    ``out_dir/<goal_id>/history-conclusions/`` corpus and returns a summary split
    into a public-safe projection and a local-only publication receipt.

    Boundary contract:
    - ``goal_id`` is validated as a single path segment before it is used as a
      directory component, so an unsafe id (``../escaped``) cannot escape
      ``out_dir``.
    - A private manifest identifies only this exporter's documents. The owned
      corpus directory is fully staged and read back before one atomic directory
      replacement, while unrelated files under ``out_dir/<goal_id>/`` are never
      moved or deleted.
    - The local filesystem output path lives only in ``local_receipt`` and is
      never part of the ``public_projection``.
    """
    safe_goal_id = validate_goal_id_path_segment(goal_id)
    history = collect_history(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=safe_goal_id,
        limit=limit,
    )
    runs = history.get("runs") or []
    goal_root = out_dir / safe_goal_id
    corpus_out = goal_root / _CORPUS_DIR
    manifest_path = corpus_out / _MANIFEST_FILE

    documents: dict[str, bytes] = {}
    digest_occurrences: dict[str, int] = {}
    skipped_noise = 0
    for run in runs:
        markdown = render_conclusion_markdown(safe_goal_id, run)
        if markdown is None:
            skipped_noise += 1
            continue
        name = _document_name(
            run,
            markdown,
            digest_occurrences=digest_occurrences,
        )
        if name in documents:
            raise RuntimeError("history export generated a duplicate document name")
        documents[name] = markdown.encode("utf-8")

    manifest = _manifest_payload(goal_id=safe_goal_id, documents=documents)
    retired = _publish_generation(
        corpus_out=corpus_out,
        documents=documents,
        manifest=manifest,
    )

    return {
        "public_projection": {
            "schema_version": HISTORY_EXPORT_SCHEMA_VERSION,
            "goal_id": safe_goal_id,
            "runs_considered": len(runs),
            "written": len(documents),
            "skipped_noise": skipped_noise,
            "retired_prior_generation": retired,
            "target_scope_hint": (
                "openviking resources scope (documents), not peer memories"
            ),
        },
        "local_receipt": {
            # Local filesystem path is intentionally kept out of the public
            # projection above.
            "out_dir": str(corpus_out),
            "manifest_path": str(manifest_path),
            "owned_files": sorted(documents),
        },
    }


def recall_history_conclusions(
    *,
    query: str,
    scope_uri: str,
    ov_bin: str = "ov",
    limit: int = 5,
    timeout_seconds: int = 25,
) -> dict[str, Any]:
    """Semantically recall exported history conclusions from a resources scope.

    This is the document-recall counterpart to the peer-preference ``_find`` in
    ``provider.py``: it targets an arbitrary ``resources`` document scope (where
    :func:`export_goal_conclusions` writes) instead of the provider-managed
    preference contract, so it does not touch or reinterpret peer memories.

    Runs one read-only ``ov find`` scoped to ``scope_uri`` and returns compact
    ``{uri, score, summary}`` items filtered to that scope. Provider-produced
    ``abstract``/``overview`` text is passed through ``public_safe_compact_text``
    and any row whose summary carries a local path or secret-like token is
    dropped, so the returned packet is public-safe end to end. Returned ``uri``
    values are constrained to the requested ``scope_uri`` prefix.
    """
    clean_query = str(query or "").strip()
    if not 1 <= len(clean_query) <= 500:
        raise ValueError("query must contain 1 to 500 characters")
    if public_safe_compact_text(clean_query, limit=500) != clean_query:
        raise ValueError("query must be public-safe compact text")
    safe_scope_uri = _safe_viking_resource_uri(scope_uri)
    if not 1 <= int(limit) <= 20:
        raise ValueError("limit must be between 1 and 20")

    try:
        completed = subprocess.run(
            [
                ov_bin,
                "find",
                "-o",
                "json",
                "-n",
                str(min(int(limit) * 3, 20)),
                "-u",
                safe_scope_uri,
                clean_query,
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("OpenViking find execution failed") from exc
    if completed.returncode != 0:
        raise RuntimeError("OpenViking find returned a non-zero exit")

    try:
        result = json.loads(completed.stdout[completed.stdout.find("{"):])
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("OpenViking find returned unparseable output") from exc

    payload = result.get("result") if isinstance(result, Mapping) else {}
    rows: list[Any] = []
    if isinstance(payload, Mapping):
        for key in ("resources", "memories"):
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend(value)

    items: list[dict[str, Any]] = []
    dropped_unsafe = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            uri = _safe_viking_resource_uri(row.get("uri"))
        except ValueError:
            dropped_unsafe += 1
            continue
        if not _is_descendant_resource_uri(uri, scope_uri=safe_scope_uri):
            continue
        score = _safe_score(row.get("score"))
        if score is None:
            dropped_unsafe += 1
            continue
        raw_summary = row.get("abstract") or row.get("overview")
        # Provider text is untrusted: sanitize end to end and drop on any hit.
        summary = public_safe_compact_text(raw_summary, limit=2_000)
        if not summary:
            dropped_unsafe += 1
            continue
        items.append(
            {
                "uri": uri,
                "score": score,
                "summary": summary,
            }
        )
    items.sort(key=lambda item: item["score"], reverse=True)
    items = items[: int(limit)]

    return {
        "schema_version": HISTORY_RECALL_SCHEMA_VERSION,
        "query": clean_query,
        "scope_uri": safe_scope_uri,
        "item_count": len(items),
        "dropped_unsafe": dropped_unsafe,
        "items": items,
    }
