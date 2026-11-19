#!/usr/bin/env python3
"""Run the app on 0.0.0.0:8000 (contract)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn  # noqa: E402

from app.main import create_app  # noqa: E402

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("IT_DB_PATH", os.path.join(_HERE, "data", "issuetrack.db"))

app = create_app(DB_PATH)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
