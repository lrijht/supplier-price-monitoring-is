"""Business logic shared by the web interface and the API (REQ-NF-031).

Directories, links and settings now; comparison, history and the feed come in
later blocks. Nothing here depends on HTTP or FastAPI.
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
from spm.services.settings import Settings, SettingsService

__all__ = [
    "PAGE_SIZE",
    "ActionRecorder",
    "Actor",
    "Conflict",
    "Directories",
    "FieldError",
    "LinkResult",
    "Material",
    "NotFound",
    "Page",
    "Settings",
    "SettingsService",
    "Supplier",
    "SupplierItem",
    "ValidationFailed",
]
