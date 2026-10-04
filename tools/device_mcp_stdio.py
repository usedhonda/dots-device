#!/usr/bin/env python3
"""Launch the device MCP regardless of the tunnel runner's working directory."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from device_mcp.server import main

if __name__ == "__main__":
    raise SystemExit(main())
