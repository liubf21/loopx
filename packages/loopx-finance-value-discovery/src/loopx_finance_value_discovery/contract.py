from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from .boundary import reject_forbidden_material


FINANCE_CASE_CONTRACT_SCHEMA_VERSION = "finance_case_contract_v1"
FINANCE_CASE_INPUT_SCHEMA_VERSION = "finance_case_gate_input_v1"
FINANCE_CASE_EVALUATION_SCHEMA_VERSION = "finance_case_gate_evaluation_v1"

MIN_GATE_COUNT = 1
MAX_GATE_COUNT = 16
VALUE_TYPES = {"boolean", "number", "string"}
OPERATORS_BY_VALUE_TYPE = {
    "boolean": {"eq"},
    "number": {"eq", "gt", "gte", "lt", "lte"},
    "string": {"eq"},
}


def _text(value: object, *, field: str, limit: int = 160) -> str:
    result = " ".join(str(value or "").split())
    if not result:
        raise ValueError(f"{field} is required")
    if len(result) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    reject_forbidden_material(result, path=field)
    return result


def _iso_date(value: object, *, field: str) -> str:
    result = _text(value, field=field, limit=40)
    try:
        if "T" in result:
            datetime.fromisoformat(result.replace("Z", "+00:00"))
        else:
            date.fromisoformat(result)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 date or datetime") from exc
    return result


def _required_boolean(
    payload: Mapping[str, Any],
    field: str,
    *,
    expected: bool,
) -> bool:
    if payload.get(field) is not expected:
        raise ValueError(f"{field} must be {str(expected).lower()}")
    return expected


def _gate_rule(value: object, *, index: int) -> dict[str, Any]:
    field = f"contract.gates[{index}]"
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    allowed = {"gate_id", "value_type", "operator", "reference_value"}
    if set(value) - allowed:
        raise ValueError(f"{field} has unsupported fields")
    value_type = _text(
        value.get("value_type"), field=f"{field}.value_type", limit=24
    )
    if value_type not in VALUE_TYPES:
        raise ValueError(f"{field}.value_type must be one of {sorted(VALUE_TYPES)}")
    operator = _text(value.get("operator"), field=f"{field}.operator", limit=16)
    if operator not in OPERATORS_BY_VALUE_TYPE[value_type]:
        raise ValueError(
            f"{field}.operator must be one of "
            f"{sorted(OPERATORS_BY_VALUE_TYPE[value_type])}"
        )
    reference = value.get("reference_value")
    if value_type == "boolean" and not isinstance(reference, bool):
        raise ValueError(f"{field}.reference_value must be a boolean")
    if value_type == "number" and (
        not isinstance(reference, (int, float)) or isinstance(reference, bool)
    ):
        raise ValueError(f"{field}.reference_value must be a number")
    if value_type == "string":
        reference = _text(
            reference, field=f"{field}.reference_value", limit=120
        )
    return {
        "gate_id": _text(value.get("gate_id"), field=f"{field}.gate_id", limit=80),
        "value_type": value_type,
        "operator": operator,
        "reference_value": reference,
    }


def validate_finance_case_contract(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("contract must be an object")
    reject_forbidden_material(value, path="contract")
    allowed = {
        "schema_version",
        "contract_id",
        "method_revision",
        "point_in_time",
        "universe_id",
        "universe_frozen",
        "identities_frozen",
        "thresholds_frozen",
        "outcome_blind",
        "public_evidence_only",
        "gates",
        "investment_advice_allowed",
        "trading_allowed",
        "automatic_promotion_allowed",
    }
    if set(value) - allowed:
        raise ValueError("contract has unsupported fields")
    if value.get("schema_version") != FINANCE_CASE_CONTRACT_SCHEMA_VERSION:
        raise ValueError(
            f"contract.schema_version must be {FINANCE_CASE_CONTRACT_SCHEMA_VERSION}"
        )
    raw_gates = value.get("gates")
    if not isinstance(raw_gates, Sequence) or isinstance(
        raw_gates, (str, bytes, bytearray)
    ):
        raise ValueError("contract.gates must be a list")
    if not MIN_GATE_COUNT <= len(raw_gates) <= MAX_GATE_COUNT:
        raise ValueError(
            f"contract.gates must contain between {MIN_GATE_COUNT} "
            f"and {MAX_GATE_COUNT} gates"
        )
    gates = [
        _gate_rule(item, index=index)
        for index, item in enumerate(raw_gates)
    ]
    gate_ids = [item["gate_id"] for item in gates]
    if len(gate_ids) != len(set(gate_ids)):
        raise ValueError("contract.gates must use unique gate ids")
    return {
        "schema_version": FINANCE_CASE_CONTRACT_SCHEMA_VERSION,
        "contract_id": _text(
            value.get("contract_id"), field="contract.contract_id", limit=96
        ),
        "method_revision": _text(
            value.get("method_revision"),
            field="contract.method_revision",
            limit=96,
        ),
        "point_in_time": _iso_date(
            value.get("point_in_time"), field="contract.point_in_time"
        ),
        "universe_id": _text(
            value.get("universe_id"), field="contract.universe_id", limit=96
        ),
        "universe_frozen": _required_boolean(
            value, "universe_frozen", expected=True
        ),
        "identities_frozen": _required_boolean(
            value, "identities_frozen", expected=True
        ),
        "thresholds_frozen": _required_boolean(
            value, "thresholds_frozen", expected=True
        ),
        "outcome_blind": _required_boolean(value, "outcome_blind", expected=True),
        "public_evidence_only": _required_boolean(
            value, "public_evidence_only", expected=True
        ),
        "gates": gates,
        "investment_advice_allowed": _required_boolean(
            value, "investment_advice_allowed", expected=False
        ),
        "trading_allowed": _required_boolean(
            value, "trading_allowed", expected=False
        ),
        "automatic_promotion_allowed": _required_boolean(
            value, "automatic_promotion_allowed", expected=False
        ),
    }


def validate_finance_case_input(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("finance case input must be an object")
    reject_forbidden_material(value)
    allowed = {"schema_version", "case_id", "contract", "observations"}
    if set(value) - allowed:
        raise ValueError("finance case input has unsupported fields")
    if value.get("schema_version") != FINANCE_CASE_INPUT_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {FINANCE_CASE_INPUT_SCHEMA_VERSION}"
        )
    observations = value.get("observations")
    if not isinstance(observations, Sequence) or isinstance(
        observations, (str, bytes, bytearray)
    ):
        raise ValueError("observations must be a list")
    return {
        "schema_version": FINANCE_CASE_INPUT_SCHEMA_VERSION,
        "case_id": _text(value.get("case_id"), field="case_id", limit=96),
        "contract": validate_finance_case_contract(value.get("contract")),
        "observations": list(observations),
    }
