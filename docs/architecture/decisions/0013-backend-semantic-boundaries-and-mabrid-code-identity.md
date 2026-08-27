# ADR 0013: Backend Semantic Boundaries and Mabrid Code Identity

- Status: Accepted
- Date: 2026-08-26
- Amends: ADR 0001, ADR 0002, ADR 0006, ADR 0009, and ADR 0010

## Context

The pre-v0.1 backend has reached the point where its three distributions and main runtime behavior
exist, but several modules still reflect the order in which features were added rather than their
durable ownership. Flat modules mix protocol values, application records, projections, ports,
runtime composition, and infrastructure adapters. Some provisional configuration and persistence
contracts advertise behavior that the runtime does not implement.

The downstream MCP path also remains split at the wrong boundary. Bridge core already owns the MCP
SDK server and raw ASGI transport primitives, while the deployable server parses MCP transport
headers, legacy SSE query parameters, and session identifiers. A future protocol profile or
stateless transport would therefore require coordinated changes in core, application service, and
server code.

The product identity is Mabrid, as accepted by ADR 0009. The backend is undergoing a coordinated
semantic refactor, so retaining obsolete Python namespaces until a second code-wide migration
would add avoidable churn. Repository hosting and source-code identity do not need to move at the
same time.

## Decision

### Adopt Mabrid for code identity

The refactored Python code uses one implicit namespace with three dependency-ordered areas:

```text
mabrid.bridge       # reusable MCP protocol bridge
mabrid.application  # Gateway, MCP Apps, and Agent Host application contexts
mabrid.server       # deployable Web/SQLite composition
```

The corresponding internal distribution names are `mabrid-bridge`, `mabrid-application`, and
`mabrid-server`. Product-owned executable, configuration, database-default, logging, and Web title
identities migrate to Mabrid as their owning modules are refactored. Pre-v0.1 code does not retain
compatibility aliases for the old package names.

Mabrid does not replace precise domain or protocol terminology. Types such as `BridgeSession`,
`EndpointPlan`, `AgentHostService`, and `ToolDescriptor` keep semantic names. Standard interfaces
such as `/mcp`, `/v1/models`, `/v1/chat/completions`, `mcp-session-id`, MCP event names, and OpenAI
object identifiers remain unchanged.

The repository directory, GitHub repository name, and Git remote are renamed manually by the
owner after the v0.1 scope is complete. That hosting migration does not require another Python API
rename.

### Preserve the dependency direction

The accepted production dependency graph remains:

```text
mabrid.server ----------------> mabrid.bridge
      `--> mabrid.application ---> mabrid.bridge
```

Bridge code never imports application or server code. Application code never imports server,
FastAPI, SQLAlchemy, YAML, or deployment configuration. Server is the composition and
infrastructure layer.

### Organize bridge core by protocol responsibility

Bridge core is reorganized into explicit internal areas:

```text
mabrid/bridge/
|-- contracts/   # immutable protocol values, plans, failures, and observations
|-- engine/      # bridge and session lifecycle
|-- downstream/  # MCP server methods, SDK conversion, ASGI, and legacy SSE
|-- routing/     # passthrough, aggregate routing, URI maps, and availability
`-- upstream/    # owner-task runtime and stdio/SSE/streamable HTTP clients
```

The core facade exports embedding contracts and lifecycle entry points. Application code does not
import internal handlers, routers, transport implementations, or SDK conversion modules.

Core protocol values preserve every supported MCP value required for transparent forwarding. In
particular, `resources/read` represents all returned contents rather than retaining only the first
item. Application timestamps and inspection status do not enter protocol value models.

### Move complete MCP transport mechanics into bridge core

Bridge core owns the framework-neutral downstream ASGI adapter, including:

- MCP HTTP method dispatch;
- `mcp-session-id` extraction and response capture;
- streamable HTTP lifecycle;
- legacy SSE endpoint and message-query normalization; and
- protocol-profile-specific stateful or stateless transport behavior.

The adapter treats the first path segment under its mount as an opaque published endpoint key. It
depends on an application-facing session broker protocol rather than on repositories or managed
topology models.

Mabrid application implements that broker. It resolves published endpoints, creates and persists
domain session records, binds transport correlation values, and closes application/core session
lifecycles. The deployable server only mounts the composed ASGI application and owns process
lifespan, CORS, health, and non-MCP HTTP APIs.

Bridge engine/session construction encapsulates downstream handlers and MCP SDK server creation.
Application code must not assemble core internals such as `ProxyHandlers` directly.

### Organize application code by bounded context

The application distribution uses context-oriented packages:

```text
mabrid/application/
|-- gateway/
|   |-- topology/    # managed definitions, revisions, plan mapping, and ports
|   |-- sessions/    # records, broker, lifecycle service, and ports
|   `-- inspection/  # durable events, snapshots, projector, and store ports
`-- agent_host/      # provider-neutral contracts, use cases, ports, and integrations
```

One context may import another only through its public facade. Package-root exports remain small;
infrastructure adapters import the owning context facade rather than one global module that
re-exports every model and port.

Core observations are projected directly into application inspection events and snapshots. An
extra journal DTO layer is retained only if it gains an independent persistence, replay, or policy
contract; it is not kept merely to copy identical data between Pydantic models.

### Keep each data model at one boundary

Models are classified by ownership:

- protocol values and wire-preservation contracts belong to bridge core;
- application commands, records, policies, events, and projections belong to their bounded
  context;
- deployment file and resolved-secret models belong to server configuration;
- SQLAlchemy rows belong to the SQLite adapter; and
- provider-specific wire documents belong to that provider integration.

Named mappers cross boundaries. Adjacent `model_dump()` and `model_validate()` calls are not used
as an implicit substitute for an owned conversion contract.

Transport configuration follows one conversion per boundary: deployment configuration creates an
application seed definition, and an immutable application revision creates a core runtime plan.
The provisional resolved-topology model layer is removed.

### Remove provisional and patch-like behavior

The pre-v0.1 refactor may reset or squash SQLite migrations and local databases. It removes fields,
tables, enums, and public exports that have no implemented behavior, including shared upstream
sessions and persisted upstream-session records until those features are designed.

Published endpoints must be explicit. Legacy default-upstream selection, implicit endpoint
creation, and configuration fields that do not affect runtime behavior are removed.

Streamable HTTP upstream clients connect only to their explicitly configured URL. Core does not
guess WSL gateways, substitute `host.docker.internal`, or issue an `OPTIONS` probe before opening
the MCP transport. Deployment configuration is responsible for environment-specific addresses.

Legacy downstream and upstream SSE remain supported as an isolated compatibility transport with
focused tests. Compatibility behavior is not spread across server and core modules.

The owner-maintained `debug_main.py` remains unchanged. Its explicit hard-coded debugging values
are intentional local workflow controls, not production fallback behavior.

### Record stable design intent in code

Every production package and module has a concise English docstring that records its owner,
boundary, dependency direction, and important invariants. Docstrings do not duplicate historical
discussion, implementation status, or line-by-line behavior. Alternatives and decision history
remain in ADRs.

## Migration Sequence

1. Freeze protocol behavior with focused characterization tests and remove patch-like network
   discovery.
2. Correct core protocol contracts, including multi-content resource reads and typed failures.
3. Reorganize bridge core and move the complete downstream ASGI adapter behind a broker port.
4. Reorganize Gateway topology, session, and inspection contexts and remove redundant DTO layers.
5. Reorganize server configuration, composition, and SQLite adapters; reset pre-v0.1 migrations.
6. Migrate Python namespaces and product-owned deployment identities to Mabrid as each owning area
   reaches its target structure.
7. Tighten package facades, update architecture documentation, and run protocol, persistence,
   typing, lint, package-build, and composed-server validation.

Each step is behavior-scoped and independently validated. Protocol changes are not hidden inside
mechanical file moves.

## Consequences

- MCP transport profile changes are contained in bridge core and its broker contract rather than
  requiring three layers to parse the same request.
- Application and persistence code consume fewer core internals and fewer global re-exports.
- Mabrid code identity is established once during the backend refactor while repository hosting can
  move later without another import migration.
- Removing speculative fields and tables may invalidate local pre-v0.1 databases; this is accepted.
- Legacy SSE remains a deliberate compatibility cost with an explicit owner and tests.
- The refactor is larger than a directory rename, but each phase has a narrow executable gate.