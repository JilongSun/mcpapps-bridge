default:
    @just --list

install:
    cd backend && uv sync
    cd frontend && pnpm install

backend:
    cd backend && uv run --package mabrid-server python -m mabrid.server.main

frontend:
    cd frontend && pnpm dev

frontend-build:
    cd frontend && pnpm build