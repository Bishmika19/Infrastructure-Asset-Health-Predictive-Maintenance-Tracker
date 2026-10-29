"""Single model registry: importing this module registers all 13 tables."""

from app.db.base import Base
from app.infrastructure.outbox.models import OutboxEvent
from app.modules.alerts.models import Alert
from app.modules.analytics.models import AnalyticsEvent
from app.modules.assets.models import Asset
from app.modules.audit.models import AuditLog
from app.modules.identity.models import User
from app.modules.inspections.models import Inspection, InspectionPhoto
from app.modules.scoring.models import HealthScoreHistory
from app.modules.work_orders.models import WorkOrder, WorkOrderStatusHistory
from app.shared.models import IdempotencyRecord
from app.worker.models import ScheduledRun

__all__ = [
    "Base",
    "Alert",
    "AnalyticsEvent",
    "Asset",
    "AuditLog",
    "HealthScoreHistory",
    "IdempotencyRecord",
    "Inspection",
    "InspectionPhoto",
    "OutboxEvent",
    "ScheduledRun",
    "User",
    "WorkOrder",
    "WorkOrderStatusHistory",
]
