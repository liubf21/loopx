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

import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...control_plane.runtime.public_safety import public_safe_compact_text
from ...history import collect_history, validate_goal_id_path_segment

HISTORY_EXPORT_SCHEMA_VERSION = "loopx_history_conclusion_export_v0"
HISTORY_RECALL_SCHEMA_VERSION = "loopx_history_conclusion_recall_v0"

_CONCLUSION_LIMIT = 400
_MAX_PROGRESS_BULLETS = 3
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")
# Bounded ISO-8601-ish timestamp: digits, T/space, colon, dot, +/- and Z only.
_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:.+\-]{1,20}Z?$")


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

    Writes one public-safe markdown per substantive run under
    ``out_dir/<goal_id>/`` and returns a summary split into a public-safe
    projection and a local-only publication receipt.

    Boundary contract:
    - ``goal_id`` is validated as a single path segment before it is used as a
      directory component, so an unsafe id (``../escaped``) cannot escape
      ``out_dir``.
    - Each generation clears the goal's prior exported markdown before writing,
      so stale conclusions do not survive when later history is empty or fully
      redacted (generation-retirement contract).
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
    goal_out = out_dir / safe_goal_id
    goal_out.mkdir(parents=True, exist_ok=True)

    # Generation retirement: remove the prior generation's exported documents so
    # a later empty/redacted history cannot leave stale conclusions behind.
    retired = 0
    for stale in goal_out.glob("*.md"):
        stale.unlink()
        retired += 1

    written = 0
    skipped_noise = 0
    for run in runs:
        markdown = render_conclusion_markdown(safe_goal_id, run)
        if markdown is None:
            skipped_noise += 1
            continue
        generated_at = _safe_generated_at(run.get("generated_at"))
        classification = public_safe_compact_text(
            run.get("classification"), limit=80
        ) or "run"
        name = _slug(f"{generated_at}-{classification}")
        (goal_out / f"{name}.md").write_text(markdown, encoding="utf-8")
        written += 1

    return {
        "public_projection": {
            "schema_version": HISTORY_EXPORT_SCHEMA_VERSION,
            "goal_id": safe_goal_id,
            "runs_considered": len(runs),
            "written": written,
            "skipped_noise": skipped_noise,
            "retired_prior_generation": retired,
            "target_scope_hint": (
                "openviking resources scope (documents), not peer memories"
            ),
        },
        "local_receipt": {
            # Local filesystem path is intentionally kept out of the public
            # projection above.
            "out_dir": str(goal_out),
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
    if not scope_uri.startswith("viking://"):
        raise ValueError("scope_uri must be a viking:// resource uri")
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
                scope_uri,
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

    scope_prefix = f"{scope_uri.rstrip('/')}/"
    items: list[dict[str, Any]] = []
    dropped_unsafe = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        uri = str(row.get("uri") or "").strip()
        if not uri.startswith(scope_prefix):
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
                "score": row.get("score"),
                "summary": summary,
            }
        )
    items.sort(key=lambda item: item.get("score") or 0.0, reverse=True)
    items = items[: int(limit)]

    return {
        "schema_version": HISTORY_RECALL_SCHEMA_VERSION,
        "query": clean_query,
        "scope_uri": scope_uri,
        "item_count": len(items),
        "dropped_unsafe": dropped_unsafe,
        "items": items,
    }
