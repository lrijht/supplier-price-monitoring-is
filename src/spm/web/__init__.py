"""Web interface: server HTML screens, Jinja2, no JavaScript (REQ-NF-015)."""

from spm.web.routes import method_not_allowed, not_found, router

__all__ = ["method_not_allowed", "not_found", "router"]
