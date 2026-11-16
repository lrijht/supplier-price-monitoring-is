"""A separate process of the system that performs one update run.

Used by the B2 tests to stop the system in the middle of a run (REQ-F-024):
the test kills this process while the run waits for a catalogue page, then
starts the system again in the test process on the same database.

Arguments: database path, action log path, technical log path, session key,
the clock moment (ISO 8601 with offset), trigger, login of the starter ("" —
none). The process imports only ``spm`` and the test client of FastAPI, which
runs the application's start-up (the database schema).
"""

from __future__ import annotations

import sys
from datetime import datetime

from fastapi.testclient import TestClient


def main(argv: list[str]) -> int:
    database, action_log, technical_log, secret, moment, trigger, started_by = argv
    from spm.app import create_app
    from spm.clock import ManualClock
    from spm.config import Config

    config = Config(
        session_secret=secret,
        database_path=database,
        action_log_path=action_log,
        technical_log_path=technical_log,
    )
    app = create_app(config, clock=ManualClock(datetime.fromisoformat(moment)))
    with TestClient(app):
        app.state.updates.run(trigger, started_by=started_by or None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
