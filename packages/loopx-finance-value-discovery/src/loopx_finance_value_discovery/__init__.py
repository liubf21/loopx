"""Finance value-discovery extension."""

from .contract import (
    FINANCE_CASE_CONTRACT_SCHEMA_VERSION,
    FINANCE_CASE_EVALUATION_SCHEMA_VERSION,
    FINANCE_CASE_INPUT_SCHEMA_VERSION,
    validate_finance_case_contract,
)
from .gates import evaluate_finance_case_gates
from .replay import (
    FINANCE_CASE_REPLAY_RECEIPT_SCHEMA_VERSION,
    build_finance_case_evaluation,
    replay_finance_case_evaluation,
)
from .reducer import (
    EVIDENCE_AXES,
    FINANCE_VALUE_DISCOVERY_CARD_SCHEMA_VERSION,
    FINANCE_VALUE_DISCOVERY_INPUT_SCHEMA_VERSION,
    FINANCE_VALUE_DISCOVERY_PACKET_SCHEMA_VERSION,
    FINANCE_VALUE_DISCOVERY_EXTENSION_PROTOCOL,
    build_finance_value_discovery_packet,
    render_finance_value_discovery_markdown,
)

__all__ = [
    "EVIDENCE_AXES",
    "FINANCE_CASE_CONTRACT_SCHEMA_VERSION",
    "FINANCE_CASE_EVALUATION_SCHEMA_VERSION",
    "FINANCE_CASE_INPUT_SCHEMA_VERSION",
    "FINANCE_CASE_REPLAY_RECEIPT_SCHEMA_VERSION",
    "FINANCE_VALUE_DISCOVERY_CARD_SCHEMA_VERSION",
    "FINANCE_VALUE_DISCOVERY_INPUT_SCHEMA_VERSION",
    "FINANCE_VALUE_DISCOVERY_PACKET_SCHEMA_VERSION",
    "FINANCE_VALUE_DISCOVERY_EXTENSION_PROTOCOL",
    "build_finance_value_discovery_packet",
    "build_finance_case_evaluation",
    "evaluate_finance_case_gates",
    "replay_finance_case_evaluation",
    "render_finance_value_discovery_markdown",
    "validate_finance_case_contract",
]
