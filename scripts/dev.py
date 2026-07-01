"""Cross-platform development launcher for the backend and frontend."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    backend_dir = root / "backend"
    frontend_dir = root / "frontend"

    backend_cmd = [sys.executable, "-m", "mcpapps_bridge.main"]
    frontend_cmd = ["pnpm", "dev"]

    backend_process = subprocess.Popen(backend_cmd, cwd=backend_dir)
    frontend_process = subprocess.Popen(frontend_cmd, cwd=frontend_dir)
    processes = [backend_process, frontend_process]

    def shutdown() -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()

    try:
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    shutdown()
                    return code
            time.sleep(0.2)
    except KeyboardInterrupt:
        shutdown()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())