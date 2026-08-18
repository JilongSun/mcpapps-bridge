# ADR 0007: Cembrid Identity and Deployment Shells

- Status: Accepted
- Date: 2026-08-18

## Context

The working name `mcpapps-bridge` described the initial MCP Apps proxy but no longer represents the
aggregate gateway, management plane, Agent Host, first-party UI, and reusable bridge core. A purely
functional name would become inaccurate again as the product evolves.

The product also needs a final deployment boundary. Enterprise and cross-network use requires a
normal Web service and container artifact. Personal use benefits from a lightweight desktop
application that owns a local service without requiring users to operate Python or Docker.

## Decision

The product brand is **Cembrid**. The name is a product identity rather than a description of one
feature. Domain-name availability does not determine the product name.

The repository, Python import packages, JavaScript packages, Rust crates, executable names, HTTP
paths, configuration keys, and protocol-facing identities are not renamed during the current
pre-v0.1 architecture migration. A coordinated post-v0.1 interface refactor will adopt the brand
after release behavior and contracts are complete. Registry names must be checked and reserved at
that time; this ADR does not claim current PyPI, npm, or crates.io ownership.

Cembrid has exactly two supported product deployment shells. New shells require a separate
product or a later amendment to this ADR.

### Web and OCI service

The v0.1 deployment remains the first and release-blocking shell:

- React frontend and Python backend communicate through explicit HTTP/WebSocket contracts during
  development.
- Production builds the frontend into static assets served by one Python Web service on one
  origin.
- One OCI image contains the frontend assets, server composition, SQLite adapter, migrations, and
  supported runtime dependencies.
- This shell supports local development, self-hosting, and enterprise cross-network deployment.
- FastAPI/Uvicorn own inbound Web lifecycle; external ingress may add TLS and network policy.

### Tauri desktop service

After v0.1, a Tauri 2 application becomes the personal desktop shell:

- Tauri embeds the compiled frontend and provides native window, tray, single-instance, updater,
  and platform packaging behavior.
- Rust is the supervisor, not a second implementation of gateway behavior.
- Nuitka compiles the Python desktop server into a platform-specific sidecar executable so users
  do not install or manage Python.
- The Rust supervisor starts the sidecar on loopback, supplies an application-owned data/config
  directory and ephemeral or reserved port, waits for readiness, and exposes the endpoint to the
  embedded frontend.
- Rust retains the child-process handle, terminates the child during normal exit or update, detects
  unexpected exit, and applies an explicit bounded restart policy.
- The desktop sidecar remains a service process with the same gateway and Agent Host application
  contracts. It does not move protocol routing, topology, SQLite, or agent behavior into Rust.
- Desktop credentials, logs, database files, and configuration live under platform application
  data locations rather than the installation directory.
- The sidecar listens on loopback only by default. Desktop IPC may bootstrap endpoint and token
  discovery, but does not replace the HTTP/MCP contracts owned by the Python service.

The desktop shell may reuse the Web frontend, but desktop-only native commands must be isolated
behind a frontend host adapter. The ordinary Web build cannot depend on Tauri APIs.

## Architecture Impact

ADR 0006's core and service packages are shared by both shells. Its current `server` package is
refined into two outer compositions after v0.1:

```text
web-server ---------> gateway-service ---------> bridge-core
     `------------------------------------------> bridge-core

desktop-sidecar ----> gateway-service ---------> bridge-core
     `------------------------------------------> bridge-core

tauri-supervisor ---> desktop-sidecar process and embedded frontend
```

The Web server owns static asset serving, public listener configuration, OCI lifecycle, and Web
deployment concerns. The desktop sidecar owns loopback defaults and supervisor-facing readiness,
shutdown, and bootstrap contracts. Shared HTTP route implementations may live in a server-adapter
module, but neither composition imports the other.

Nuitka and Tauri are distribution adapters. They do not enter bridge core or gateway service
dependencies.

## v0.1 Scope

ADR 0004 remains unchanged. Version 0.1 ships the Web/OCI service and first-party Web UI. Tauri,
Rust supervision, Nuitka compilation, desktop installers, desktop updates, and product-wide rename
work are post-v0.1. The current refactor should preserve extension points for the desktop shell but
must not delay the existing release gates.

## Consequences

- Cembrid can grow without repeatedly renaming itself after individual features.
- Enterprise and personal distribution have explicit owners without introducing Electron.
- Python remains the single implementation of gateway and Agent Host behavior.
- The desktop package adds Rust, Tauri, Nuitka, signing, platform CI, sidecar compatibility, and
  child-process lifecycle work after v0.1.
- Sharing core/service contracts prevents the desktop edition from becoming a divergent product,
  while separate outer compositions keep Web and native lifecycle concerns isolated.

## Implementation Status

As of 2026-08-18:

- **Decision complete:** product identity and the two supported deployment shells are fixed.
- **Partial:** the Web server, frontend, and SQLite composition exist in source form.
- **Pending for v0.1:** the OCI image, static frontend serving, readiness, and release validation.
- **Deferred until after v0.1:** coordinated Cembrid rename and the complete Tauri/Nuitka desktop
  shell.
