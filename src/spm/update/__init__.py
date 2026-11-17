"""Price updates: fetching pages, parsers, runs and the scheduler.

``UpdateRunner`` implements the port ``RunLauncher`` of ``services``
(docs/architecture.md, section 5).
"""

from spm.update.runner import UpdateRunner

__all__ = ["UpdateRunner"]
