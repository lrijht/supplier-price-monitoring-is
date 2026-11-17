"""Business logic shared by the web interface and the API (REQ-NF-031).

Directories, links, settings and runs as users see them; comparison, history,
the feed and the items that need attention (``views``). Nothing here depends on
HTTP or FastAPI.
"""

from spm.services.actions import ActionRecorder, Actor
from spm.services.directories import (
    MATERIAL,
    PARSER,
    SUPPLIER,
    SUPPLIER_ITEM,
    Directories,
    LinkResult,
    Material,
    Supplier,
    SupplierItem,
)
from spm.services.errors import Conflict, FieldError, NotFound, ValidationFailed
from spm.services.ordering import PAGE_SIZE, Page
from spm.services.runs import (
    RUN,
    VOLUME_ACCEPTANCE,
    LaunchResult,
    Run,
    RunLauncher,
    RunLogEntry,
    Runs,
    SupplierUpdateStatus,
    VolumeAcceptance,
)
from spm.services.settings import SETTINGS, Settings, SettingsService
from spm.services.views import (
    EVENT_KINDS,
    PERIODS,
    AttentionItem,
    ComparisonListRow,
    ComparisonRow,
    Event,
    MaterialComparison,
    PriceHistory,
    Views,
)

__all__ = [
    "EVENT_KINDS",
    "MATERIAL",
    "PAGE_SIZE",
    "PARSER",
    "PERIODS",
    "RUN",
    "SETTINGS",
    "SUPPLIER",
    "SUPPLIER_ITEM",
    "VOLUME_ACCEPTANCE",
    "ActionRecorder",
    "Actor",
    "AttentionItem",
    "ComparisonListRow",
    "ComparisonRow",
    "Conflict",
    "Directories",
    "Event",
    "FieldError",
    "LaunchResult",
    "LinkResult",
    "Material",
    "MaterialComparison",
    "NotFound",
    "Page",
    "PriceHistory",
    "Run",
    "RunLauncher",
    "RunLogEntry",
    "Runs",
    "Settings",
    "SettingsService",
    "Supplier",
    "SupplierItem",
    "SupplierUpdateStatus",
    "ValidationFailed",
    "Views",
    "VolumeAcceptance",
]
