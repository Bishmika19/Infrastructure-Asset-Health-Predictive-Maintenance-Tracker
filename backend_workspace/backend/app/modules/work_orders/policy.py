"""Framework-free Case authorization and edit-matrix policy."""

from __future__ import annotations

from typing import Mapping

from app.core.errors import CaseComplete, Forbidden, InvalidTransition, ValidationFailed
from app.modules.work_orders.domain import is_next_transition
from app.modules.work_orders.models import WorkOrder
from app.shared.principal import Principal


class WorkOrderPolicy:
    """Evaluate Case authorization against the locked current order."""

    # PUBLIC_INTERFACE
    def can_create(self, principal: Principal) -> None:
        """Require the Asset Manager role for Case creation."""
        if not principal.is_asset_manager:
            raise Forbidden("Only an Asset Manager can create a Case")

    # PUBLIC_INTERFACE
    def can_update(
        self, principal: Principal, order: WorkOrder, changes: Mapping[str, object]
    ) -> None:
        """Enforce the LLD's manager edit matrix and own-order crew transitions."""
        if order.status == "Complete":
            raise CaseComplete()

        fields = set(changes)
        requested_status = changes.get("status")
        if principal.is_maintenance_crew:
            if fields != {"status"} or not isinstance(requested_status, str):
                raise Forbidden("Maintenance Crew may only advance an assigned Case")
            if order.status not in {"Assigned", "In Progress"}:
                raise Forbidden("Maintenance Crew may only advance an assigned or in-progress Case")
            if order.assignee_id != principal.user_id:
                raise Forbidden("Maintenance Crew may only advance their assigned Case")
            if not is_next_transition(order.status, requested_status):
                raise InvalidTransition("Only the next forward status is permitted")
            return

        if not principal.is_asset_manager:
            raise Forbidden("Your role does not permit this Case update")

        if requested_status is not None:
            if not isinstance(requested_status, str) or not is_next_transition(
                order.status, requested_status
            ):
                raise InvalidTransition("Only the next forward status is permitted")

        if "assignee_id" in fields:
            requested_assignee = changes["assignee_id"]
            if order.status == "Open":
                return
            if order.status == "Assigned" and requested_assignee is not None:
                return
            if requested_assignee is None:
                raise ValidationFailed("assigneeId cannot be cleared after Open")
            raise InvalidTransition("Assignee changes are permitted only in Open or Assigned")
