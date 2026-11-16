"""Supplier simulator: a separate test-environment app (REQ-NF-026...REQ-NF-029).

It lives outside /src; the system never imports it (REQ-NF-007).
"""

from simulator.app import DEFAULT_DATA_PATH, create_app

__all__ = ["DEFAULT_DATA_PATH", "create_app"]
