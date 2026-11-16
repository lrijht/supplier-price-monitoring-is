"""Run the simulator on the loopback address.

``python -m simulator [port] [data-file]``; defaults: 8001 and the shipped
data file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

from simulator.app import DEFAULT_DATA_PATH, create_app


def main(argv: list[str]) -> None:
    port = int(argv[0]) if argv else 8001
    data_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_DATA_PATH
    uvicorn.run(create_app(data_path), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main(sys.argv[1:])
