"""Backend entry points for the mcpfront bridge host."""

from __future__ import annotations

import uvicorn

from mcpfront_bridge.api import create_app

app = create_app()


def main() -> None:
    """Run the local bridge control plane for early development."""
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
