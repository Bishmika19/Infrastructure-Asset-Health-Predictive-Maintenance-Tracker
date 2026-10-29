"""Versioned ``/api/v1`` router; module routers are mounted here.

Router-level dependencies apply to every module route: unknown or repeated query
parameters are rejected (400) and responses are marked ``private, no-store``.
Domain routers (assets, scoring/alerts, inspections, work orders, history) are
added to ``MODULE_ROUTERS`` as each module is implemented. No placeholder
business endpoints are registered.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends

from app.modules.alerts.router import router as alerts_router
from app.modules.assets.router import router as assets_router
from app.modules.history.router import router as history_router
from app.modules.identity.router import router as identity_router
from app.modules.inspections.router import router as inspections_router
from app.modules.work_orders.router import router as work_orders_router
from app.shared.deps import set_no_store
from app.shared.query_guard import reject_bad_query_params

API_V1_PREFIX = "/api/v1"

# Identity first; completed domain modules follow in rollout dependency order.
MODULE_ROUTERS: List[APIRouter] = [
    identity_router,
    assets_router,
    alerts_router,
    inspections_router,
    work_orders_router,
    history_router,
]


# PUBLIC_INTERFACE
def build_api_v1_router() -> APIRouter:
    """Build the ``/api/v1`` router that includes every registered module router."""
    router = APIRouter(
        prefix=API_V1_PREFIX,
        dependencies=[Depends(reject_bad_query_params), Depends(set_no_store)],
    )
    for module_router in MODULE_ROUTERS:
        router.include_router(module_router)
    return router
