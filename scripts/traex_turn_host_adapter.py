#!/usr/bin/env python3
"""Thin TraeX host adapter for the LoopX governed Turn contract.

LoopX runs this adapter with one ``loopx_turn_host_request_v0`` JSON object on
stdin. The adapter:

1. extracts the bounded action text from the Turn envelope,
2. invokes one headless ``traex exec`` in the governed workspace,
3. asks the model to end with a compact public-safe result block,
4. emits exactly one ``loopx_turn_result_v0`` JSON object on stdout.

It does not read goal/todo state, build prompts from todo ids, write LoopX
state, spend quota, or validate its own work. Task body delivery and authority
stay in ``loopx turn run-once``; this is a dumb translation layer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

LOOPX_TURN_HOST_REQUEST_SCHEMA = "loopx_turn_host_request_v0"
LOOPX_TURN_RESULT_SCHEMA = "loopx_turn_result_v0"
COMPLETED_PHASES = ["host_execute", "typed_result"]

ACCEPTED_RESULT_KINDS = {
    "validated_progress",
    "repair_required",
    "replan_required",
    "user_action_required",
    "wait",
}
MATERIAL_KINDS = {"validated_progress", "repair_required", "replan_required"}

TEXT_LIMITS = {
    "classification": 120,
    "recommended_action": 1_200,
    "next_action": 1_200,
    "vision_unchanged_reason": 240,
    "summary": 400,
}

# Lines emitted by the TraeX CLI transport/hooks that are not model output.
_NOISE_PREFIXES = ("hook:", "INFO", "WARNING", "ERROR: Reconnecting")
_RESULT_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL,
)


def _bounded(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def extract_action_text(request: Mapping[str, Any]) -> str:
    """Return the bounded, control-plane-authored task body for the host."""

    envelope = request.get("turn_envelope")
    if not isinstance(envelope, Mapping):
        return ""
    action = envelope.get("action") if isinstance(envelope.get("action"), Mapping) else {}

    for candidate in (
        action.get("recommended_action"),
        action.get("primary_action"),
    ):
        text = _bounded(candidate, limit=TEXT_LIMITS["recommended_action"])
        if text:
            return text

    selected = action.get("selected_todo")
    if isinstance(selected, Mapping):
        text = _bounded(selected.get("text"), limit=TEXT_LIMITS["recommended_action"])
        if text:
            return text
    return ""


def render_prompt(action_text: str) -> str:
    """Wrap one bounded action in the TraeX result-block framing.

    The model owns execution; the trailing block is the only channel the adapter
    reads back as a typed candidate. It stays public-safe and bounded.
    """

    return (
        "You are executing one bounded LoopX-governed work segment.\n"
        "Perform exactly the task below in the current workspace. Do not read or "
        "modify anything outside it.\n\n"
        f"Task:\n{action_text}\n\n"
        "When finished, output ONLY a final JSON code block "
        "(```json ... ```) with these public-safe fields:\n"
        "- result_kind: one of validated_progress | repair_required | "
        "replan_required | user_action_required | wait\n"
        "- classification: short label (<=120 chars)\n"
        "- summary: what changed or why stopped (<=400 chars)\n"
        "- next_action: the concrete next step (<=1200 chars)\n"
        "Use repair_required when the task is sound but a recoverable defect "
        "blocks it, replan_required when this route is exhausted, and "
        "wait/user_action_required when no material write is safe. "
        "Do not include raw transcripts, credentials, or absolute local paths."
    )


def _strip_noise(stdout: str) -> str:
    kept = [
        line
        for line in stdout.splitlines()
        if not any(line.startswith(prefix) for prefix in _NOISE_PREFIXES)
    ]
    return "\n".join(kept).strip()


def parse_result_block(stdout: str) -> dict[str, Any] | None:
    """Extract the model's final JSON result block from TraeX output."""

    cleaned = _strip_noise(stdout)
    candidates: list[str] = []
    for match in _RESULT_BLOCK_RE.finditer(cleaned):
        candidates.append(match.group(1))
    # Fallback: the last {...} object in output, if no fenced block was found.
    if not candidates:
        last = cleaned.rfind("{")
        if last != -1:
            candidates.append(cleaned[last:])
    for raw in reversed(candidates):
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict) and str(value.get("result_kind") or "") in ACCEPTED_RESULT_KINDS:
            return value
    return None


def build_result(
    request: Mapping[str, Any],
    candidate: Mapping[str, Any] | None,
    *,
    fallback_reason: str = "",
) -> dict[str, Any]:
    """Shape a model result block into a valid loopx_turn_result_v0."""

    turn_key = str(request.get("turn_key") or "")
    if candidate is None:
        # Fail closed: no typed material claim means a stop, never fabricated
        # progress. This spends no quota.
        return {
            "schema_version": LOOPX_TURN_RESULT_SCHEMA,
            "turn_key": turn_key,
            "result_kind": "wait",
            "completed_phases": list(COMPLETED_PHASES),
            "classification": "no_typed_host_result",
            "next_action": _bounded(
                fallback_reason
                or "TraeX returned no typed result block; rerun or inspect the host session.",
                limit=TEXT_LIMITS["next_action"],
            ),
            "vision_unchanged_reason": _bounded(
                "host adapter could not confirm a material change",
                limit=TEXT_LIMITS["vision_unchanged_reason"],
            ),
        }

    kind = str(candidate.get("result_kind") or "").strip()
    result: dict[str, Any] = {
        "schema_version": LOOPX_TURN_RESULT_SCHEMA,
        "turn_key": turn_key,
        "result_kind": kind,
        "completed_phases": list(COMPLETED_PHASES),
    }
    for field, limit in TEXT_LIMITS.items():
        if field == "vision_unchanged_reason":
            continue
        value = candidate.get(field)
        text = _bounded(value, limit=limit) if value else ""
        if text:
            result[field] = text

    if kind in MATERIAL_KINDS:
        result["delivery_batch_scale"] = "single_surface"
        result["delivery_outcome"] = "outcome_progress"
        # Material results require these bounded text fields; fill them from
        # adjacent fields if the model returned a sparse block.
        if not result.get("recommended_action"):
            result["recommended_action"] = _bounded(
                result.get("next_action") or result.get("classification") or kind,
                limit=TEXT_LIMITS["recommended_action"],
            )
        if not result.get("next_action"):
            result["next_action"] = _bounded(
                result.get("recommended_action"),
                limit=TEXT_LIMITS["next_action"],
            )
        if not result.get("classification"):
            result["classification"] = _bounded(
                kind, limit=TEXT_LIMITS["classification"]
            )
    # This adapter has no goal-vision packet, so the executor treats the path
    # delta as unchanged and requires a bounded reason for material results.
    result["vision_unchanged_reason"] = _bounded(
        candidate.get("vision_unchanged_reason")
        or (
            "host reported material work without a goal vision replan packet"
            if kind in MATERIAL_KINDS
            else "host reported no material change"
        ),
        limit=TEXT_LIMITS["vision_unchanged_reason"],
    )
    return result


def run_traex(
    prompt: str,
    *,
    traex_bin: str,
    workspace: Path,
    permission_mode: str,
    model: str | None,
    timeout_seconds: float,
    skip_git_repo_check: bool,
) -> subprocess.CompletedProcess[str]:
    argv: list[str] = [traex_bin, "exec"]
    if skip_git_repo_check:
        argv.append("--skip-git-repo-check")
    argv.extend(["--permission-mode", permission_mode])
    if model:
        argv.extend(["-m", model])
    argv.append(prompt)
    return subprocess.run(
        argv,
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=max(1.0, timeout_seconds),
        check=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traex-bin", default="traex")
    parser.add_argument("--workspace", default=os.getcwd())
    parser.add_argument(
        "--permission-mode",
        default="bypass_permissions",
        choices=("bypass_permissions", "custom"),
        help="exec cannot prompt for approvals, so default/copy-on-write are rejected",
    )
    parser.add_argument("-m", "--model", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument(
        "--no-skip-git-repo-check",
        dest="skip_git_repo_check",
        action="store_false",
    )
    args = parser.parse_args(argv)

    try:
        request = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"adapter: invalid request JSON on stdin: {exc}", file=sys.stderr)
        return 2
    if not isinstance(request, dict) or request.get("schema_version") != LOOPX_TURN_HOST_REQUEST_SCHEMA:
        print("adapter: stdin is not a loopx_turn_host_request_v0 object", file=sys.stderr)
        return 2

    action_text = extract_action_text(request)
    if not action_text:
        print(json.dumps(build_result(request, None)), flush=True)
        return 0

    try:
        completed = run_traex(
            render_prompt(action_text),
            traex_bin=args.traex_bin,
            workspace=Path(args.workspace),
            permission_mode=args.permission_mode,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            skip_git_repo_check=args.skip_git_repo_check,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Non-zero / non-JSON stdout makes the driver classify host_failure.
        print(f"adapter: traex exec failed: {type(exc).__name__}", file=sys.stderr)
        return 1

    if completed.returncode != 0:
        print(
            f"adapter: traex exited {completed.returncode}: "
            f"{completed.stderr.strip()[:400]}",
            file=sys.stderr,
        )
        return completed.returncode if completed.returncode > 0 else 1

    candidate = parse_result_block(completed.stdout or "")
    result = build_result(request, candidate)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
