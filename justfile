default:
    @just --list

install:
    cd backend && uv sync
    cd frontend && pnpm install

backend:
    cd backend && uv run python -m mcpapps_bridge.main

frontend:
    cd frontend && pnpm dev

dev:
    cd backend && uv run python ../scripts/dev.py

frontend-build:
    cd frontend && pnpm build