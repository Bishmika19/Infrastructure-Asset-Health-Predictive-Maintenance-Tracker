"""Focused unit tests for Case lifecycle, authorization policy, and API schemas."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.core.errors import CaseComplete, Forbidden, InvalidTransition, ValidationFailed
from app.modules.work_orders.domain import CASE_STATUSES, is_next_transition, next_status
from app.modules.work_orders.models import WorkOrder
from app.modules.work_orders.policy import WorkOrderPolicy
from app.modules.work_orders.schemas import CreateCase, UpdateCase
from app.shared.principal import ROLE_ASSET_MANAGER, ROLE_MAINTENANCE_CREW, Principal


def _principal(role: str) -> Principal:
    """Create a synthetic authenticated principal for policy-only tests."""
    return Principal(user_id=uuid.uuid4(), username=f"{role}-user", role=role)


def _order(
    *,
    status: str = "Open",
    assignee_id: uuid.UUID | None = None,
    version: int = 1,
) -> WorkOrder:
    """Build an unpersisted Case aggregate containing the fields used by policy checks."""
    return WorkOrder(
        id=uuid.uuid4(),
        asset_id="unit-asset",
        alert_id=uuid.uuid4(),
        asset_snapshot={},
        fault_description="Synthetic fault",
        priority="High",
        assignee_id=assignee_id,
        status=status,
        created_by=uuid.uuid4(),
        version=version,
    )


def test_transition_map_exposes_only_the_three_forward_edges() -> None:
    """The public state machine permits exactly Open→Assigned→In Progress→Complete."""
    assert CASE_STATUSES == ("Open", "Assigned", "In Progress", "Complete")
    assert next_status("Open") == "Assigned"
    assert next_status("Assigned") == "In Progress"
    assert next_status("In Progress") == "Complete"
    assert next_status("Complete") is None
    assert next_status("unknown") is None

    assert is_next_transition("Open", "Assigned")
    assert is_next_transition("Assigned", "In Progress")
    assert is_next_transition("In Progress", "Complete")
    assert not is_next_transition("Open", "In Progress")
    assert not is_next_transition("Assigned", "Assigned")
    assert not is_next_transition("Complete", "Open")


def test_only_asset_managers_can_create_cases() -> None:
    """Case creation remains manager-only regardless of the caller's other identity data."""
    policy = WorkOrderPolicy()

    policy.can_create(_principal(ROLE_ASSET_MANAGER))
    with pytest.raises(Forbidden):
        policy.can_create(_principal(ROLE_MAINTENANCE_CREW))


def test_crew_can_only_advance_their_own_assigned_or_in_progress_case() -> None:
    """Crew cannot assign Open Cases, edit metadata, or advance another user's Case."""
    policy = WorkOrderPolicy()
    crew = _principal(ROLE_MAINTENANCE_CREW)
    other_crew = _principal(ROLE_MAINTENANCE_CREW)

    with pytest.raises(Forbidden):
        policy.can_update(
            crew,
            _order(status="Open", assignee_id=crew.user_id),
            {"status": "Assigned"},
        )
    with pytest.raises(Forbidden):
        policy.can_update(
            crew,
            _order(status="Assigned", assignee_id=crew.user_id),
            {"priority": "Critical"},
        )
    with pytest.raises(Forbidden):
        policy.can_update(
            other_crew,
            _order(status="Assigned", assignee_id=crew.user_id),
            {"status": "In Progress"},
        )

    policy.can_update(
        crew,
        _order(status="Assigned", assignee_id=crew.user_id),
        {"status": "In Progress"},
    )
    policy.can_update(
        crew,
        _order(status="In Progress", assignee_id=crew.user_id),
        {"status": "Complete"},
    )
    with pytest.raises(InvalidTransition):
        policy.can_update(
            crew,
            _order(status="Assigned", assignee_id=crew.user_id),
            {"status": "Complete"},
        )


def test_manager_edit_matrix_enforces_assignment_and_terminal_rules() -> None:
    """Managers may change metadata but must preserve lifecycle and assignment invariants."""
    policy = WorkOrderPolicy()
    manager = _principal(ROLE_ASSET_MANAGER)
    crew_id = uuid.uuid4()

    policy.can_update(manager, _order(status="Open"), {"assignee_id": crew_id})
    policy.can_update(manager, _order(status="Assigned", assignee_id=crew_id), {"priority": "Low"})
    policy.can_update(
        manager,
        _order(status="Assigned", assignee_id=crew_id),
        {"assignee_id": uuid.uuid4()},
    )

    with pytest.raises(ValidationFailed):
        policy.can_update(
            manager,
            _order(status="Assigned", assignee_id=crew_id),
            {"assignee_id": None},
        )
    with pytest.raises(InvalidTransition):
        policy.can_update(manager, _order(status="Open"), {"status": "In Progress"})
    with pytest.raises(CaseComplete):
        policy.can_update(manager, _order(status="Complete", assignee_id=crew_id), {"priority": "Low"})


def test_create_case_schema_is_strict_trimmed_and_camel_case() -> None:
    """Create schema accepts contract aliases and rejects unsupported client-controlled data."""
    case = CreateCase.model_validate(
        {
            "assetId": "  PUMP-100  ",
            "faultDescription": "  Seal leakage  ",
            "priority": "High",
        }
    )

    assert case.asset_id == "PUMP-100"
    assert case.fault_description == "Seal leakage"
    assert case.assignee_id is None
    assert case.alert_id is None

    with pytest.raises(ValidationError):
        CreateCase.model_validate(
            {
                "assetId": "PUMP-100",
                "faultDescription": "Leak",
                "priority": "High",
                "version": 99,
            }
        )


def test_update_case_requires_a_nonempty_sparse_patch_and_preserves_explicit_null() -> None:
    """Sparse PATCH rejects empty bodies while retaining explicit Open-assignee clearing."""
    with pytest.raises(ValidationError):
        UpdateCase.model_validate({})

    update = UpdateCase.model_validate({"assigneeId": None})
    assert update.model_fields_set == {"assignee_id"}
    assert update.model_dump(exclude_unset=True) == {"assignee_id": None}

    with pytest.raises(ValidationError):
        UpdateCase.model_validate({"status": "Cancelled"})
