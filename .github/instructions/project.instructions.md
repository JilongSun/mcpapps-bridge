---
description: "Stable project-wide product and engineering constraints. Architecture state and ownership live in ADRs and architecture documentation."
applyTo: "**"
---
# Project Standards

## Scope

This project has two core pillars: an MCP Apps Gateway and an adapter-driven Agent Host with
first-party MCP Apps UI support. A deployment may disable the Agent Host, but both capabilities
belong to the product.

- Preserve transparent MCP and MCP Apps behavior for downstream agent runtimes and models.
- Treat aggregate gateway behavior, management contracts, Agent Host runtime contracts, and MCP
	Apps lifecycle as release-critical.
- Do not expand v0.1 scope into speculative channels or post-v0.1 deployment shells.

## Architecture

- Follow the accepted dependency direction: server may depend on gateway service and bridge core;
	gateway service may depend on bridge core; lower packages never import the server.
- Keep protocol bridging, application use cases, and deployment infrastructure in their documented
	ownership boundaries.
- Keep agent-specific behavior out of reusable bridge core modules.
- Treat accepted ADRs and `docs/architecture/` as authoritative for current ownership and migration
	status. Do not duplicate implementation snapshots in instruction files.

## Conventions

- Use precise MCP terminology such as `bridge`, `host`, `adapter`, `session`, and `resource`.
- Prefer typed, contract-first boundaries and small explicit implementations.
- Preserve cross-platform behavior and avoid OS-specific path or shell assumptions.
- Do not expose management, persistence, routing, or debugging concepts in model-visible MCP
	descriptions unless the protocol contract requires them.

## Testing

- Scale tests with behavior risk. Preserve protocol characterization coverage during architecture
	migration.
- Use controlled fixtures for bridge and protocol tests rather than live agents or MCP servers.
