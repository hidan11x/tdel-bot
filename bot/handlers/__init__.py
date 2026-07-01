from typing import Any

_user_context: dict[int, dict[str, Any]] = {}

from .user import router as user_router
from .scan import router as scan_router
from .watchlist import router as watchlist_router
from .alerts import router as alerts_router
from .charts import router as charts_router
from .subscriptions import router as subscriptions_router
from .top import router as top_router
from .admin import router as admin_router
from .comparison import router as comparison_router
from .tickets import router as tickets_router
from .heatmap import router as heatmap_router

__all__ = [
    "user_router",
    "scan_router",
    "watchlist_router",
    "alerts_router",
    "charts_router",
    "subscriptions_router",
    "top_router",
    "admin_router",
    "comparison_router",
    "tickets_router",
    "heatmap_router",
    "_user_context",
]
