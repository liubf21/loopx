from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .pr_gate_reconcile import reconcile_issue_fix_pr_review
from .pr_lifecycle import fetch_github_pr_lifecycle_payload
from .pr_review_ack import (
    load_issue_fix_pr_review_ack_receipts,
    open_issue_fix_pr_review_ack_receipts,
)


PR_REVIEW_PRE_QUOTA_SCHEMA_VERSION = "issue_fix_pr_review_pre_quota_v0"
MetadataFetcher = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _fetch_github_metadata(binding: Mapping[str, Any]) -> Mapping[str, Any]:
    return fetch_github_pr_lifecycle_payload(
        {
            "repo": binding.get("repository"),
            "number": binding.get("pr_number"),
        }
    )


def reconcile_issue_fix_pr_reviews_before_quota(
    *,
    registry_path: Path,
    runtime_root: Path,
    runtime_root_arg: str | None,
    goal_id: str,
    agent_id: str,
    project: Path | None,
    available_capabilities: Sequence[str],
    metadata_fetcher: MetadataFetcher | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    capabilities = {
        str(value).strip().lower()
        for value in available_capabilities
        if str(value).strip()
    }
    receipts = load_issue_fix_pr_review_ack_receipts(
        runtime_root=runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
    )
    open_receipts = open_issue_fix_pr_review_ack_receipts(
        receipts=receipts,
        registry_path=registry_path,
        goal_id=goal_id,
        agent_id=agent_id,
        project=project,
    )
    result: dict[str, Any] = {
        "ok": True,
        "schema_version": PR_REVIEW_PRE_QUOTA_SCHEMA_VERSION,
        "mode": "heartbeat_pre_quota",
        "goal_id": goal_id,
        "agent_id": agent_id,
        "ack_receipt_count": len(receipts),
        "open_binding_count": len(open_receipts),
        "attempted_count": 0,
        "reconciled_count": 0,
        "write_performed": False,
        "external_read_performed": False,
        "quota_decision_mutated": False,
        "items": [],
    }
    if not open_receipts:
        result["status"] = "no_open_acknowledged_reviews"
        return result
    if "network" not in capabilities:
        result["status"] = "capability_unavailable"
        result["required_capabilities"] = ["network"]
        return result

    fetcher = metadata_fetcher or _fetch_github_metadata
    for receipt in open_receipts:
        binding = receipt.get("binding")
        if not isinstance(binding, Mapping):
            continue
        item = {
            "todo_id": binding.get("todo_id"),
            "provider": binding.get("provider"),
            "pr_ref": binding.get("pr_ref"),
            "ack_receipt_id": receipt.get("receipt_id"),
            "write_performed": False,
        }
        if binding.get("provider") != "github":
            item["status"] = "unsupported_provider"
            result["items"].append(item)
            continue
        result["attempted_count"] += 1
        try:
            provider_payload = dict(fetcher(binding))
            result["external_read_performed"] = True
            reconciliation = reconcile_issue_fix_pr_review(
                registry_path=registry_path,
                runtime_root_arg=runtime_root_arg,
                goal_id=goal_id,
                todo_id=str(binding.get("todo_id") or ""),
                agent_id=agent_id,
                project=project,
                url=str(binding.get("permalink") or ""),
                ack_receipt=receipt,
                provider_payload=provider_payload,
                execute=True,
                generated_at=generated_at,
            )
            item.update(
                {
                    "status": (
                        "reconciled"
                        if reconciliation.get("reconciled")
                        else str(reconciliation.get("skip_reason") or "not_reconciled")
                    ),
                    "terminal": reconciliation.get("terminal") is True,
                    "write_performed": reconciliation.get("write_performed") is True,
                }
            )
            if reconciliation.get("reconciled"):
                result["reconciled_count"] += 1
            if reconciliation.get("write_performed"):
                result["write_performed"] = True
        except Exception as exc:
            item.update(
                {
                    "status": "reconciliation_error",
                    "error_type": type(exc).__name__,
                }
            )
        result["items"].append(item)
    result["status"] = (
        "reconciled" if result["reconciled_count"] else "checked_no_terminal_match"
    )
    return result


__all__ = [
    "PR_REVIEW_PRE_QUOTA_SCHEMA_VERSION",
    "reconcile_issue_fix_pr_reviews_before_quota",
]
