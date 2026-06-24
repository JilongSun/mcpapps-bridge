"""Backend entry points for the mcpapps bridge host."""

from __future__ import annotations

import uvicorn

from mcpapps_bridge.api import create_app

app = create_app()


def main() -> None:
    """Run the local bridge control plane for early development."""
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
