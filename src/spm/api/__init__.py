"""REST API under /api/v1 (REQ-NF-031, spec/openapi.yaml)."""

from spm.api.errors import API_PREFIX, install_error_handlers, internal_error_response
from spm.api.routes import router

__all__ = ["API_PREFIX", "install_error_handlers", "internal_error_response", "router"]
