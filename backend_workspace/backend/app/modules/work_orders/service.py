"""Transactional Case service; Cases are the API alias over work orders."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Mapping, Optional

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import (
    AlertMismatch,
    AssetInactive,
    AssetNotFlagged,
    NotFound,
    ValidationFailed,
    VersionMismatch,
)
from app.db.unit_of_work import run_in_transaction
from app.infrastructure.outbox.writer import OutboxWriter
from app.modules.alerts.repository import AlertRepository
from app.modules.analytics.emitter import (
    WORK_ORDER_CREATED,
    WORK_ORDER_STATUS_CHANGED,
    AnalyticsEmitter,
)
from app.modules.assets.repository import AssetRepository
from app.modules.audit.writer import (
    EVENT_WORK_ORDER_CREATED,
    EVENT_WORK_ORDER_UPDATED,
    AuditWriter,
)
from app.modules.identity.repository import UserRepository
from app.modules.work_orders.models import WorkOrder
from app.modules.work_orders.policy import WorkOrderPolicy
from app.modules.work_orders.repository import WorkOrderRepository
from app.modules.work_orders.schemas import Case
from app.shared.concurrency import format_etag
from app.shared.idempotency import IdempotencyStore, StoredResponse, request_fingerprint
from app.shared.pagination import DEFAULT_PAGE_LIMIT, decode_cursor, encode_cursor
from app.shared.principal import ROLE_MAINTENANCE_CREW, Principal

CASE_CURSOR_KIND = "cases"
CASE_CREATE_OPERATION = "cases.create"


@dataclass(frozen=True)
class CasePageResult:
    """One Case page and its signed continuation cursor."""

    items: list[WorkOrder]
    next_cursor: Optional[str]


class WorkOrderService:
    """Coordinate Case persistence without importing FastAPI."""

    def __init__(self, settings: Settings, factory: sessionmaker[Session]) -> None:
        self._settings = settings
        self._factory = factory
        self._policy = WorkOrderPolicy()

    # PUBLIC_INTERFACE
    def create(
        self, principal: Principal, values: Mapping[str, object], idempotency_key: str
    ) -> WorkOrder | StoredResponse:
        """Create a Case and persist an exact replay response atomically."""
        self._policy.can_create(principal)
        fingerprint = request_fingerprint(values)

        def work(session: Session) -> WorkOrder | StoredResponse:
            store = IdempotencyStore(session, self._settings.idempotency_ttl_s)
            replay = store.lookup(
                principal.user_id, CASE_CREATE_OPERATION, idempotency_key, fingerprint
            )
            if replay is not None:
                return replay

            asset_id = str(values["asset_id"])
            asset = AssetRepository(session).lock(asset_id)
            if asset is None:
                raise NotFound("Asset not found")
            if asset.status != "active":
                raise AssetInactive()
            alert = AlertRepository(session).get_open(asset_id, lock=True)
            if alert is None:
                raise AssetNotFlagged()

            supplied_alert = values.get("alert_id")
            if supplied_alert is not None and supplied_alert != alert.id:
                raise AlertMismatch()

            assignee_id = values.get("assignee_id")
            if assignee_id is not None:
                self._validate_crew(
                    UserRepository(session).lock_many([assignee_id]), assignee_id
                )

            now = dt.datetime.now(dt.timezone.utc)
            order = WorkOrder(
                asset_id=asset.asset_id,
                alert_id=alert.id,
                asset_snapshot={
                    "asset_id": asset.asset_id,
                    "asset_type": asset.asset_type,
                    "location": asset.location,
                    "installation_date": asset.installation_date.isoformat(),
                    "manufacturer": asset.manufacturer,
                    "last_service_date": (
                        asset.last_service_date.isoformat() if asset.last_service_date else None
                    ),
                },
                fault_description=str(values["fault_description"]),
                priority=str(values["priority"]),
                assignee_id=assignee_id,
                status="Open",
                created_by=principal.user_id,
                created_at=now,
                updated_at=now,
            )
            repo = WorkOrderRepository(session)
            repo.add(order)
            repo.add_status_history(order, None, principal.user_id, now)
            AuditWriter(session).record(
                EVENT_WORK_ORDER_CREATED,
                principal.actor,
                entity_type="work_order",
                entity_id=str(order.id),
                metadata={"assetId": order.asset_id, "priority": order.priority},
            )
            AnalyticsEmitter(session).emit(
                WORK_ORDER_CREATED,
                {
                    "asset_id": order.asset_id,
                    "work_order_id": str(order.id),
                    "priority": order.priority,
                    "assignee_id": str(order.assignee_id) if order.assignee_id else None,
                },
            )
            OutboxWriter(session).enqueue(
                "work_order_created",
                "work_order",
                str(order.id),
                {"caseId": str(order.id), "assetId": order.asset_id, "actorId": str(principal.user_id)},
            )
            body = Case.model_validate(order).model_dump(mode="json", by_alias=True)
            headers = {
                "ETag": format_etag(order.version),
                "Location": f"/api/v1/cases/{order.id}",
            }
            store.save(
                principal.user_id,
                CASE_CREATE_OPERATION,
                idempotency_key,
                fingerprint,
                StoredResponse(201, body, headers),
            )
            return order

        return run_in_transaction(self._factory, work)

    # PUBLIC_INTERFACE
    def update(
        self,
        principal: Principal,
        case_id: uuid.UUID,
        expected_version: int,
        changes: Mapping[str, object],
    ) -> WorkOrder:
        """Apply one authorized sparse Case update under a strong version precondition."""
        def work(session: Session) -> WorkOrder:
            repo = WorkOrderRepository(session)
            existing = repo.get(case_id)
            if existing is None:
                raise NotFound("Case not found")
            AssetRepository(session).lock(existing.asset_id)
            relevant_users = [user_id for user_id in (existing.assignee_id, changes.get("assignee_id")) if user_id]
            users = UserRepository(session).lock_many(relevant_users)
            order = repo.lock(case_id)
            if order is None:
                raise NotFound("Case not found")
            if order.version != expected_version:
                raise VersionMismatch()

            self._policy.can_update(principal, order, changes)
            if "assignee_id" in changes and changes["assignee_id"] is not None:
                self._validate_crew(users, changes["assignee_id"])

            desired_status = changes.get("status", order.status)
            if desired_status == "Assigned" and (changes.get("assignee_id", order.assignee_id) is None):
                raise ValidationFailed("assigneeId is required when assigning a Case")

            changed = {
                field: value for field, value in changes.items() if getattr(order, field) != value
            }
            if not changed:
                return order

            previous_status = order.status
            for field, value in changed.items():
                setattr(order, field, value)
            now = dt.datetime.now(dt.timezone.utc)
            order.version += 1
            order.updated_at = now
            if "status" in changed:
                repo.add_status_history(order, previous_status, principal.user_id, now)
                AnalyticsEmitter(session).emit(
                    WORK_ORDER_STATUS_CHANGED,
                    {
                        "work_order_id": str(order.id),
                        "previous_status": previous_status,
                        "new_status": order.status,
                        "actor_role": principal.role,
                    },
                )
                OutboxWriter(session).enqueue(
                    "work_order_status_changed",
                    "work_order",
                    str(order.id),
                    {
                        "caseId": str(order.id),
                        "previousStatus": previous_status,
                        "newStatus": order.status,
                        "actorId": str(principal.user_id),
                    },
                )
            AuditWriter(session).record(
                EVENT_WORK_ORDER_UPDATED,
                principal.actor,
                entity_type="work_order",
                entity_id=str(order.id),
                metadata={"changedFields": sorted(changed)},
            )
            session.flush()
            return order

        return run_in_transaction(self._factory, work)

    # PUBLIC_INTERFACE
    def fetch(self, case_id: uuid.UUID) -> WorkOrder:
        """Fetch one Case or raise ``NotFound`` without exposing database details."""
        def work(session: Session) -> WorkOrder:
            order = WorkOrderRepository(session).get(case_id)
            if order is None:
                raise NotFound("Case not found")
            return order

        return run_in_transaction(self._factory, work)

    # PUBLIC_INTERFACE
    def list(
        self,
        *,
        asset_id: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        assignee_id: Optional[uuid.UUID] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: Optional[str] = None,
    ) -> CasePageResult:
        """List Cases in stable descending creation-time keyset order."""
        filters = {
            "assetId": asset_id,
            "status": status,
            "priority": priority,
            "assigneeId": str(assignee_id) if assignee_id else None,
        }
        after = None
        if cursor:
            decoded = decode_cursor(
                self._settings.auth_token_secret, cursor, CASE_CURSOR_KIND, filters
            )
            try:
                last = decoded["last"]
                after = (dt.datetime.fromisoformat(last[0]), uuid.UUID(last[1]))
            except (IndexError, TypeError, ValueError):
                from app.core.errors import InvalidCursor
                raise InvalidCursor() from None

        def work(session: Session) -> CasePageResult:
            rows = WorkOrderRepository(session).list_page(
                asset_id=asset_id,
                status=status,
                priority=priority,
                assignee_id=assignee_id,
                after=after,
                limit=limit + 1,
            )
            items = rows[:limit]
            next_cursor = None
            if len(rows) > limit and items:
                tail = items[-1]
                next_cursor = encode_cursor(
                    self._settings.auth_token_secret,
                    CASE_CURSOR_KIND,
                    [tail.created_at.isoformat(), str(tail.id)],
                    filters,
                )
            return CasePageResult(items=items, next_cursor=next_cursor)

        return run_in_transaction(self._factory, work)

    @staticmethod
    def _validate_crew(users: Mapping[uuid.UUID, object], assignee_id: object) -> None:
        """Require a supplied assignee to resolve to an active Maintenance Crew user."""
        user = users.get(assignee_id)
        if (
            user is None
            or getattr(user, "role", None) != ROLE_MAINTENANCE_CREW
            or not getattr(user, "is_active", False)
        ):
            raise ValidationFailed("assigneeId must identify an active Maintenance Crew user")
