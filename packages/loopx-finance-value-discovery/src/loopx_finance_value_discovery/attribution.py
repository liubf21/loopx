from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from .boundary import reject_forbidden_material
from .contract import validate_finance_case_contract
from .replay import canonical_json_bytes, canonical_sha256

FINANCE_BETA_ATTRIBUTION_INPUT_SCHEMA_VERSION = "finance_beta_attribution_input_v1"
FINANCE_BETA_ATTRIBUTION_SCHEMA_VERSION = "finance_beta_attribution_v1"
FINANCE_BETA_ATTRIBUTION_REPLAY_SCHEMA_VERSION = "finance_beta_attribution_replay_v1"

EXPLAINED_BETA_COMPONENTS = (
    "market",
    "rate",
    "sector",
    "narrow_peer",
    "cycle",
    "event",
)
ATTRIBUTION_STATES = {"observed", "missing", "conflict"}


def _text(value: object, *, field: str, limit: int = 320) -> str:
    result = " ".join(str(value or "").split())
    if not result:
        raise ValueError(f"{field} is required")
    if len(result) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    reject_forbidden_material(result, path=field)
    return result


def _decimal(value: object, *, field: str) -> Decimal:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite number")
    return result


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _evidence_refs(value: object, *, field: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field} must be a list")
    if len(value) > 12:
        raise ValueError(f"{field} must contain at most 12 items")
    refs = [
        _text(item, field=f"{field}[{index}]", limit=120)
        for index, item in enumerate(value)
    ]
    if len(refs) != len(set(refs)):
        raise ValueError(f"{field} must use unique evidence refs")
    return refs


def _component(value: object, *, index: int) -> dict[str, Any]:
    field = f"components[{index}]"
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    allowed = {
        "component_id",
        "observation_state",
        "contribution",
        "evidence_refs",
        "reason",
    }
    if set(value) - allowed:
        raise ValueError(f"{field} has unsupported fields")
    state = _text(
        value.get("observation_state"),
        field=f"{field}.observation_state",
        limit=24,
    )
    if state not in ATTRIBUTION_STATES:
        raise ValueError(
            f"{field}.observation_state must be one of {sorted(ATTRIBUTION_STATES)}"
        )
    contribution = value.get("contribution")
    if state == "observed":
        normalized_contribution = _decimal(contribution, field=f"{field}.contribution")
    else:
        if contribution is not None:
            raise ValueError(f"{field}.contribution is only valid when state=observed")
        normalized_contribution = None
    refs = _evidence_refs(value.get("evidence_refs"), field=f"{field}.evidence_refs")
    if state == "observed" and not refs:
        raise ValueError(f"{field} observed contributions require evidence_refs")
    if state == "conflict" and len(refs) < 2:
        raise ValueError(f"{field} conflicts require at least two evidence_refs")
    return {
        "component_id": _text(
            value.get("component_id"), field=f"{field}.component_id", limit=40
        ),
        "observation_state": state,
        "contribution": (
            _decimal_text(normalized_contribution)
            if normalized_contribution is not None
            else None
        ),
        "evidence_refs": refs,
        "reason": _text(value.get("reason"), field=f"{field}.reason"),
    }


def build_finance_beta_attribution(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("finance beta attribution input must be an object")
    reject_forbidden_material(value)
    allowed = {
        "schema_version",
        "attribution_id",
        "attribution_model_id",
        "component_order_frozen",
        "unit",
        "contract",
        "total_move",
        "components",
    }
    if set(value) - allowed:
        raise ValueError("finance beta attribution input has unsupported fields")
    if value.get("schema_version") != FINANCE_BETA_ATTRIBUTION_INPUT_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {FINANCE_BETA_ATTRIBUTION_INPUT_SCHEMA_VERSION}"
        )
    if value.get("component_order_frozen") is not True:
        raise ValueError("component_order_frozen must be true")
    if value.get("unit") != "return_fraction":
        raise ValueError("unit must be return_fraction")
    contract = validate_finance_case_contract(value.get("contract"))
    total_move = _decimal(value.get("total_move"), field="total_move")
    raw_components = value.get("components")
    if not isinstance(raw_components, Sequence) or isinstance(
        raw_components, (str, bytes, bytearray)
    ):
        raise ValueError("components must be a list")
    components = [
        _component(item, index=index) for index, item in enumerate(raw_components)
    ]
    component_ids = [item["component_id"] for item in components]
    if component_ids != list(EXPLAINED_BETA_COMPONENTS):
        raise ValueError(
            "components must exactly match the frozen market/rate/sector/"
            "narrow_peer/cycle/event order"
        )

    missing = [
        item["component_id"]
        for item in components
        if item["observation_state"] == "missing"
    ]
    conflicts = [
        item["component_id"]
        for item in components
        if item["observation_state"] == "conflict"
    ]
    complete = not missing and not conflicts
    explained = (
        sum(
            (
                Decimal(str(item["contribution"]))
                for item in components
                if item["contribution"] is not None
            ),
            Decimal(0),
        )
        if complete
        else None
    )
    residual = total_move - explained if explained is not None else None
    attribution = {
        "ok": True,
        "schema_version": FINANCE_BETA_ATTRIBUTION_SCHEMA_VERSION,
        "attribution_id": _text(
            value.get("attribution_id"), field="attribution_id", limit=96
        ),
        "attribution_model_id": _text(
            value.get("attribution_model_id"),
            field="attribution_model_id",
            limit=96,
        ),
        "contract": contract,
        "unit": "return_fraction",
        "total_move": _decimal_text(total_move),
        "components": components
        + [
            {
                "component_id": "residual",
                "observation_state": "computed" if complete else "not_computable",
                "contribution": _decimal_text(residual)
                if residual is not None
                else None,
                "evidence_refs": [],
                "reason": (
                    "Computed as total_move minus all six explained components."
                    if complete
                    else (
                        "Residual is unavailable while an explained component "
                        "is missing or conflicting."
                    )
                ),
            }
        ],
        "explained_sum": _decimal_text(explained) if explained is not None else None,
        "residual": _decimal_text(residual) if residual is not None else None,
        "disposition": "complete" if complete else "insufficient_evidence",
        "missing_component_ids": missing,
        "conflicting_component_ids": conflicts,
        "boundary": {
            "public_evidence_only": True,
            "outcome_blind": True,
            "investment_advice": False,
            "trading_allowed": False,
            "automatic_promotion_allowed": False,
        },
    }
    replay = {
        "schema_version": FINANCE_BETA_ATTRIBUTION_REPLAY_SCHEMA_VERSION,
        "contract_sha256": canonical_sha256(contract),
        "input_sha256": canonical_sha256(value),
        "attribution_sha256": canonical_sha256(attribution),
        "canonicalization": "json_sort_keys_compact_ascii_v1",
    }
    return {**attribution, "replay": replay}


def replay_finance_beta_attribution(
    value: object,
    expected: object,
) -> dict[str, Any]:
    if not isinstance(expected, Mapping):
        raise ValueError("expected attribution must be an object")
    replayed = build_finance_beta_attribution(value)
    expected_replay = expected.get("replay")
    if not isinstance(expected_replay, Mapping):
        raise ValueError("expected attribution requires a replay receipt")
    for field in ("contract_sha256", "input_sha256", "attribution_sha256"):
        if expected_replay.get(field) != replayed["replay"][field]:
            raise ValueError(f"replay {field} mismatch")
    if canonical_json_bytes(expected) != canonical_json_bytes(replayed):
        raise ValueError("replay attribution bytes mismatch")
    return {
        "ok": True,
        "schema_version": FINANCE_BETA_ATTRIBUTION_REPLAY_SCHEMA_VERSION,
        "replay_verified": True,
        "contract_sha256": replayed["replay"]["contract_sha256"],
        "input_sha256": replayed["replay"]["input_sha256"],
        "attribution_sha256": replayed["replay"]["attribution_sha256"],
    }
