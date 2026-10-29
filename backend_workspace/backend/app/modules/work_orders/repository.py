"""Case/work-order persistence; repository methods never commit."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import List, Optional

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.modules.work_orders.models import WorkOrder, WorkOrderStatusHistory


class WorkOrderRepository:
    """Data access for work orders and their append-only status history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, case_id: uuid.UUID) -> Optional[WorkOrder]:
        """Return one Case without acquiring a mutation lock."""
        return self._session.get(WorkOrder, case_id)

    def lock(self, case_id: uuid.UUID) -> Optional[WorkOrder]:
        """Lock and refresh one Case for an optimistic-concurrency mutation."""
        return self._session.execute(
            select(WorkOrder)
            .where(WorkOrder.id == case_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    def add(self, order: WorkOrder) -> WorkOrder:
        """Stage and flush a new Case so its generated UUID is available."""
        self._session.add(order)
        self._session.flush()
        return order

    def add_status_history(
        self,
        order: WorkOrder,
        previous_status: Optional[str],
        actor_id: uuid.UUID,
        changed_at: dt.datetime,
    ) -> WorkOrderStatusHistory:
        """Append one initial or forward-transition lifecycle record."""
        history = WorkOrderStatusHistory(
            work_order_id=order.id,
            previous_status=previous_status,
            new_status=order.status,
            actor_id=actor_id,
            changed_at=changed_at,
            order_version=order.version,
        )
        self._session.add(history)
        self._session.flush()
        return history

    def list_page(
        self,
        *,
        asset_id: Optional[str],
        status: Optional[str],
        priority: Optional[str],
        assignee_id: Optional[uuid.UUID],
        after: Optional[tuple[dt.datetime, uuid.UUID]],
        limit: int,
    ) -> List[WorkOrder]:
        """Return a fixed-order Case page after a descending creation-time keyset."""
        statement = select(WorkOrder)
        if asset_id is not None:
            statement = statement.where(WorkOrder.asset_id == asset_id)
        if status is not None:
            statement = statement.where(WorkOrder.status == status)
        if priority is not None:
            statement = statement.where(WorkOrder.priority == priority)
        if assignee_id is not None:
            statement = statement.where(WorkOrder.assignee_id == assignee_id)
        if after is not None:
            statement = statement.where(tuple_(WorkOrder.created_at, WorkOrder.id) < after)
        return list(
            self._session.execute(
                statement.order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc()).limit(limit)
            ).scalars()
        )
