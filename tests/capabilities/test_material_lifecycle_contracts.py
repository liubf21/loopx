from __future__ import annotations

import pytest

from loopx.capabilities.material_lifecycle import (
    build_material_lifecycle_architecture_packet,
    build_material_lifecycle_receipt,
    build_material_migration_plan,
    build_material_rerank_apply_receipt,
    build_material_rerank_proposal,
    build_material_store_inventory,
)

OBSERVED_AT = "2026-07-25T16:30:00+00:00"


def inventory_packet() -> dict[str, object]:
    return build_material_store_inventory(
        goal_id="goal:material-example",
        store_id="store:learning-materials",
        store_revision="revision:42",
        observed_at=OBSERVED_AT,
        source_snapshot_ref="snapshot:revision-42",
        backup_ref="backup:revision-42",
        source_digest="sha256:0123456789abcdef",
        lifecycle_counts={
            "candidate": 30,
            "active": 10,
            "archived": 200,
            "unread": 5,
            "carryover": 2,
        },
        parse_error_refs=["parse-error:1"],
        stable_ids_verified=True,
        backup_verified=True,
    )


def test_architecture_positions_material_lifecycle_as_default_off_sibling() -> None:
    packet = build_material_lifecycle_architecture_packet()

    assert packet["schema_version"] == "material_lifecycle_architecture_v0"
    assert packet["capability"] == {
        "capability_id": "material_lifecycle",
        "scope": "goal",
        "default_enabled": False,
        "creates_authority": False,
        "mutates_core_state": False,
    }
    assert packet["sibling_capabilities"]["decision_context"].startswith(
        "supplies revisioned evidence"
    )
    assert packet["provider_boundaries"]["raw_material_store"] == (
        "private_external_authority"
    )


def test_inventory_is_deterministic_read_only_and_content_free() -> None:
    first = inventory_packet()
    second = inventory_packet()

    assert first == second
    assert first["item_count"] == 247
    assert first["source_mutation_authorized"] is False
    assert first["raw_content_captured"] is False
    assert str(first["inventory_ref"]).startswith("material-inventory-")


def test_inventory_rejects_raw_locations_and_unknown_states() -> None:
    with pytest.raises(ValueError, match="opaque reference"):
        build_material_store_inventory(
            goal_id="goal:material-example",
            store_id="store:learning-materials",
            store_revision="revision:42",
            observed_at=OBSERVED_AT,
            source_snapshot_ref="https://example.invalid/private",
            backup_ref="backup:revision-42",
            source_digest="sha256:0123456789abcdef",
            lifecycle_counts={"candidate": 1},
            stable_ids_verified=True,
            backup_verified=True,
        )
    with pytest.raises(ValueError, match="unsupported states"):
        build_material_store_inventory(
            goal_id="goal:material-example",
            store_id="store:learning-materials",
            store_revision="revision:42",
            observed_at=OBSERVED_AT,
            source_snapshot_ref="snapshot:revision-42",
            backup_ref="backup:revision-42",
            source_digest="sha256:0123456789abcdef",
            lifecycle_counts={"raw_content": 1},
            stable_ids_verified=True,
            backup_verified=True,
        )


def test_migration_plan_requires_dual_read_owner_gate_and_rollback() -> None:
    inventory = inventory_packet()
    plan = build_material_migration_plan(
        goal_id="goal:material-example",
        plan_id="plan:migrate-v0",
        inventory_ref=str(inventory["inventory_ref"]),
        source_revision="revision:42",
        target_schema="material_store_v0",
        observed_at=OBSERVED_AT,
        backup_ref="backup:revision-42",
        rollback_ref="rollback:revision-42",
        expected_item_count=247,
        protected_material_refs=["material:pinned"],
    )

    assert plan["phases"] == [
        "snapshot",
        "inventory",
        "dual_read",
        "reconcile",
        "owner_gate",
        "apply",
        "rollback_ready",
    ]
    assert plan["owner_gate_required"] is True
    assert plan["source_mutation_authorized"] is False


def test_archive_and_reactivation_preserve_stable_references() -> None:
    archived = build_material_lifecycle_receipt(
        goal_id="goal:material-example",
        receipt_id="receipt:archive-1",
        material_ref="material:42",
        from_state="active",
        to_state="archived",
        observed_at=OBSERVED_AT,
        source_ref="source:42",
        source_revision="revision:42",
        transition_authority_ref="decision-outcome:archive-1",
        evidence_refs=["evidence:artifact-created"],
        artifact_ref="artifact:note-42",
        archive_ref="archive:42",
        decision_evidence_ref="decision-evidence-0123456789abcdef",
    )
    reactivated = build_material_lifecycle_receipt(
        goal_id="goal:material-example",
        receipt_id="receipt:reactivate-1",
        material_ref="material:42",
        from_state="archived",
        to_state="active",
        observed_at=OBSERVED_AT,
        source_ref="source:42",
        source_revision="revision:43",
        transition_authority_ref="policy:reactivate-reviewed-archive",
        archive_ref="archive:42",
    )

    assert archived["source_reference_preserved"] is True
    assert reactivated["material_ref"] == archived["material_ref"]
    assert reactivated["archive_ref"] == archived["archive_ref"]
    assert reactivated["raw_content_captured"] is False


def test_lifecycle_rejects_invalid_or_unreferenced_archive_transitions() -> None:
    with pytest.raises(ValueError, match="archive_ref is required"):
        build_material_lifecycle_receipt(
            goal_id="goal:material-example",
            receipt_id="receipt:archive-1",
            material_ref="material:42",
            from_state="active",
            to_state="archived",
            observed_at=OBSERVED_AT,
            source_ref="source:42",
            source_revision="revision:42",
            transition_authority_ref="decision-outcome:archive-1",
        )
    with pytest.raises(ValueError, match="unsupported material lifecycle transition"):
        build_material_lifecycle_receipt(
            goal_id="goal:material-example",
            receipt_id="receipt:skip-1",
            material_ref="material:42",
            from_state="unread",
            to_state="archived",
            observed_at=OBSERVED_AT,
            source_ref="source:42",
            source_revision="revision:42",
            transition_authority_ref="decision-outcome:skip-1",
            archive_ref="archive:42",
        )


def test_rerank_proposal_is_bounded_and_decision_referenced() -> None:
    proposal = build_material_rerank_proposal(
        goal_id="goal:material-example",
        proposal_id="proposal:rerank-1",
        inventory_ref=str(inventory_packet()["inventory_ref"]),
        decision_evidence_ref="decision-evidence-0123456789abcdef",
        observed_at=OBSERVED_AT,
        target_window_size=30,
        max_moved_items=3,
        max_rank_displacement=5,
        protected_material_refs=["material:pinned"],
        moves=[
            {
                "material_ref": "material:42",
                "from_rank": 8,
                "to_rank": 4,
                "reason_code": "current_objective_fit",
                "evidence_refs": ["evidence:decision-1"],
            }
        ],
    )

    assert proposal["no_change"] is False
    assert proposal["apply_authorized"] is False
    assert proposal["constraints"]["max_moved_items"] == 3
    assert proposal["moves"][0]["material_ref"] == "material:42"


def test_rerank_supports_no_change_and_rejects_unbounded_moves() -> None:
    no_change = build_material_rerank_proposal(
        goal_id="goal:material-example",
        proposal_id="proposal:no-change",
        inventory_ref=str(inventory_packet()["inventory_ref"]),
        decision_evidence_ref="decision-evidence-0123456789abcdef",
        observed_at=OBSERVED_AT,
        target_window_size=30,
        max_moved_items=3,
        max_rank_displacement=5,
        no_change_reason="Current evidence does not justify changing the shortlist.",
    )
    assert no_change["no_change"] is True

    with pytest.raises(ValueError, match="protected"):
        build_material_rerank_proposal(
            goal_id="goal:material-example",
            proposal_id="proposal:protected",
            inventory_ref=str(inventory_packet()["inventory_ref"]),
            decision_evidence_ref="decision-evidence-0123456789abcdef",
            observed_at=OBSERVED_AT,
            target_window_size=30,
            max_moved_items=3,
            max_rank_displacement=5,
            protected_material_refs=["material:pinned"],
            moves=[
                {
                    "material_ref": "material:pinned",
                    "from_rank": 2,
                    "to_rank": 1,
                    "reason_code": "move_protected",
                }
            ],
        )
    with pytest.raises(ValueError, match="max_rank_displacement"):
        build_material_rerank_proposal(
            goal_id="goal:material-example",
            proposal_id="proposal:too-far",
            inventory_ref=str(inventory_packet()["inventory_ref"]),
            decision_evidence_ref="decision-evidence-0123456789abcdef",
            observed_at=OBSERVED_AT,
            target_window_size=30,
            max_moved_items=3,
            max_rank_displacement=5,
            moves=[
                {
                    "material_ref": "material:42",
                    "from_rank": 20,
                    "to_rank": 1,
                    "reason_code": "unbounded_move",
                }
            ],
        )


def test_apply_receipt_requires_owner_gate_validation_and_rollback() -> None:
    applied = build_material_rerank_apply_receipt(
        goal_id="goal:material-example",
        receipt_id="receipt:apply-1",
        proposal_ref="material-rerank-0123456789abcdef",
        observed_at=OBSERVED_AT,
        status="applied",
        before_revision="revision:42",
        after_revision="revision:43",
        owner_gate_ref="gate:rerank-1",
        validation_ref="validation:rerank-1",
        applied_material_refs=["material:42"],
        rollback_ref="rollback:revision-42",
    )
    assert applied["status"] == "applied"
    assert applied["raw_content_captured"] is False

    with pytest.raises(ValueError, match="rollback_ref"):
        build_material_rerank_apply_receipt(
            goal_id="goal:material-example",
            receipt_id="receipt:apply-2",
            proposal_ref="material-rerank-0123456789abcdef",
            observed_at=OBSERVED_AT,
            status="applied",
            before_revision="revision:42",
            after_revision="revision:43",
            owner_gate_ref="gate:rerank-1",
            validation_ref="validation:rerank-1",
            applied_material_refs=["material:42"],
        )


def test_no_change_apply_receipt_preserves_revision() -> None:
    receipt = build_material_rerank_apply_receipt(
        goal_id="goal:material-example",
        receipt_id="receipt:no-change",
        proposal_ref="material-rerank-0123456789abcdef",
        observed_at=OBSERVED_AT,
        status="no_change",
        before_revision="revision:42",
        after_revision="revision:42",
        owner_gate_ref="gate:rerank-1",
        validation_ref="validation:rerank-1",
    )

    assert receipt["status"] == "no_change"
    assert receipt["applied_material_refs"] == []
