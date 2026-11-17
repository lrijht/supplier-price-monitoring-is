"""Business logic shared by the web interface and the API (REQ-NF-031).

Directories, links, settings and runs as users see them; comparison, history
and the feed screen come in block B3. Nothing here depends on HTTP or FastAPI.
"""

from spm.services.actions import ActionRecorder, Actor
from spm.services.directories import (
    Directories,
    LinkResult,
    Material,
    Supplier,
    SupplierItem,
)
from spm.services.errors import Conflict, FieldError, NotFound, ValidationFailed
from spm.services.ordering import PAGE_SIZE, Page
from spm.services.runs import (
    LaunchResult,
    Run,
    RunLauncher,
    RunLogEntry,
    Runs,
    SupplierUpdateStatus,
    VolumeAcceptance,
)
from spm.services.settings import Settings, SettingsService

__all__ = [
    "PAGE_SIZE",
    "ActionRecorder",
    "Actor",
    "Conflict",
    "Directories",
    "FieldError",
    "LaunchResult",
    "LinkResult",
    "Material",
    "NotFound",
    "Page",
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
    "VolumeAcceptance",
]
