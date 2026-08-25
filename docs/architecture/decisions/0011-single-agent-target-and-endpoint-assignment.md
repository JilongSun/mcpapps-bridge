# ADR 0011: Single Agent Target and Gateway Endpoint Assignment

- Status: Accepted
- Date: 2026-08-25
- Amends: ADR 0003, ADR 0006, and ADR 0010

## Context

The first Agent Host slice connects one independently deployed Hermes process through its
OpenAI-compatible HTTP API. Hermes advertises the configured agent through `GET /v1/models` as if
it were a model, while its Chat Completions handler can accept a caller-provided model value
without that value necessarily selecting a separately managed foundation model.

This exposes three distinctions that the initial one-adapter implementation does not yet model
clearly:

1. An externally deployed agent runtime, its OpenAI-facing model identity, and a live agent run are
   different concepts.
2. OpenAI compatibility describes a request and response family, but Hermes still adds runtime
   semantics such as session headers, tool-progress events, approvals, and detached runs.
3. The Gateway endpoint consumed by Hermes is configured manually in Hermes. The product must know
   the intended relationship without taking ownership of Hermes configuration or pretending that
   an Agent Host request proves which MCP session handled a later tool call.

A general runtime registry, model catalog, and per-run protocol selector would address possible
future deployments, but the first release has one Agent Host runtime and does not need that
complexity. At the same time, leaving the Agent Host and Gateway topology unrelated would make the
management model unable to explain which aggregate MCP endpoint an agent is expected to use.

The concrete Hermes adapter currently lives in the deployable server package. That placement keeps
infrastructure outside the provider-neutral application modules, but it also makes the reusable
runtime integration an implementation detail of one Web deployment shell. Future source, OCI,
desktop-sidecar, or embedded process compositions should be able to reuse the same Agent Runtime
integration without importing the FastAPI server application.

## Decision

### One managed Agent Target for v0.1

The v0.1 management and application model uses an **Agent Target** as the selectable unit.

An Agent Target combines:

- one configured external agent runtime instance;
- one runtime integration kind, initially Hermes over OpenAI Chat Completions;
- one stable target identifier exposed as the OpenAI-compatible model identity; and
- one declared Gateway endpoint assignment.

The target is not a live process identifier, an Agent Run, or an independently managed foundation
model. Each invocation creates a new Agent Run against the configured target.

The first implementation composes exactly one Agent Target. It does not introduce separate runtime
and model repositories, a multi-target registry, load balancing, or model-to-runtime routing. An
adapter may discover or cache the remote model string needed for a wire request, but that value is
adapter state rather than a separate product-managed model entity.

`GET /v1/models` advertises the target identifier through the OpenAI `model` representation. In
`POST /v1/chat/completions`, the `model` field is a compatibility selector for the single target,
not a foreign key into a model catalog. The initial server may accept any non-empty model value and
resolve it to the sole target because no alternative target exists. The canonical response and
management identity use the configured target identifier. Strict unknown-model rejection is
deferred until multiple targets make selection meaningful.

### One communication interface for the initial target

The first Agent Target uses non-streaming OpenAI Chat Completions over HTTP. OpenAI SDK types own
the standard wire contract, while the Hermes runtime integration owns Hermes-specific request,
response, header, event, and capability behavior.

The initial design does not add per-run selection among Chat Completions, Responses, Hermes native
runs, ACP, or other interfaces. Streaming Chat Completions is the next extension of the selected
interface, not a general interface-selection system. Additional interfaces may later be composed
inside a target integration without changing the provider-neutral Agent Host run contracts.

### Declared assignment to one stable Gateway endpoint

Each enabled Agent Target declares exactly one managed Gateway endpoint assignment for v0.1. The
assignment references the stable endpoint identity or slug used in `/mcp/{endpoint_slug}`, not an
immutable endpoint revision. A new MCP transport session still captures the current immutable
revision according to ADR 0008.

The endpoint is the target's intended MCP tool and resource surface. Aggregate mode allows that one
stable endpoint to represent multiple upstream MCP servers while Hermes remains configured with a
single MCP URL.

The assignment is **declared desired state**:

- The management surface can show which MCP endpoint belongs to the Agent Target and the exact URL
  that an operator must configure in Hermes.
- Configuration and readiness checks can verify that the assigned endpoint exists and is enabled.
- The project does not modify Hermes configuration, inject MCP servers into each Chat Completions
  request, launch Hermes, or hot-reload Hermes when the assignment changes.
- The assignment does not prove that the external Hermes process was configured correctly or that
  a particular Agent Run caused a particular Gateway MCP session. Runtime verification and
  run-to-MCP-session correlation require later explicit contracts.

An assigned endpoint remains an ordinary MCP endpoint and can still be reached by compatible MCP
clients. Assignment records product intent; it does not create exclusive network access control.

### Ownership across service and deployment packages

The `gateway-service` distribution owns the reusable Agent Host capability, including:

- provider-neutral Agent Target, run, event, and endpoint-assignment contracts;
- Agent Host orchestration and outbound runtime ports; and
- isolated reusable outbound Agent Runtime integrations under an Agent Host integration or
  `runtimes` module.

A concrete Hermes integration may depend on the official OpenAI SDK and HTTP/SSE libraries while
remaining isolated from provider-neutral service modules. `AgentHostService` depends only on its
runtime port and never imports Hermes-specific code.

The deployable server remains a deployment shell and composition root. It owns:

- FastAPI inbound OpenAI-compatible and management routes;
- YAML and environment-secret resolution;
- construction and lifecycle wiring of the configured Agent Target;
- Uvicorn, SQLite adapters, migrations, logging, static assets, and deployment defaults.

This amends ADR 0006 and ADR 0010, which placed concrete outbound agent adapters in the server
package. The three-package dependency direction does not change: server may import service and
core, service may import core, and neither lower package imports server.

## Consequences

- The first release has one clear selection and management identity instead of premature runtime,
  model, and route catalogs.
- OpenAI `model` remains wire-compatible but does not claim to identify a separately managed
  foundation model.
- Gateway management can present the intended Agent Target-to-endpoint relationship even though
  Hermes configuration remains deliberately non-invasive and manual.
- Endpoint topology changes continue to follow restart-applied revision semantics without changing
  the stable URL configured in Hermes.
- Deployment shells can reuse Agent Runtime integrations without importing the FastAPI server
  package.
- The service distribution gains concrete integration dependencies, but those dependencies stay in
  isolated outbound modules and do not enter provider-neutral contracts.
- Declared assignment can drift from real Hermes configuration until a future verification
  capability is designed.

## Rejected Alternatives

### Separate runtime and model catalogs in v0.1

A runtime serving many selectable models may require separate identities later. The initial Hermes
deployment presents one agent as one model and gains no useful behavior from separate catalogs.

### A general Agent Route entity now

A route combining runtime, model, interface, and endpoint would anticipate multi-target selection
before the product has a second target. The Agent Target and its endpoint assignment preserve the
necessary identity and relationship without introducing that abstraction yet.

### Dynamic MCP configuration injection

Passing Gateway topology into each agent request or rewriting Hermes configuration would make the
integration invasive, couple the Agent Host to Hermes administration, and conflict with the stable
aggregate endpoint model. Operators configure the assigned endpoint in Hermes explicitly.

### Keep reusable outbound runtimes in the Web server package

This would make FastAPI's deployment package the reuse boundary for source, OCI, desktop-sidecar,
and embedded compositions. The server remains the composition root, but reusable outbound runtime
integrations belong with the Agent Host capability they implement.

## Explicitly Deferred

- Multiple Agent Targets and runtime registries.
- Multiple managed models per runtime.
- Strict OpenAI model-name routing and namespaced model identifiers.
- Per-run interface selection and fallback among Chat Completions, Responses, Hermes native runs,
  ACP, or other protocols.
- Automated Hermes MCP configuration and configuration-drift verification.
- Exclusive endpoint ownership or authorization derived from target assignment.
- Proven Agent Run, Hermes session, Gateway bridge session, and MCP App correlation.

## Implementation Status

As of 2026-08-25, this decision is **Partial**.

Implemented foundations:

- one configured Agent Target with a canonical OpenAI model identity and endpoint assignment;
- one `AgentHostService` runtime port that normalizes incoming model selectors to that target;
- SDK-compatible model-list discovery and non-streaming Chat Completions, with the sole remote
  Hermes model cached as runtime state;
- one reusable Hermes/OpenAI runtime integration isolated under `gateway-service.agent_host`;
- composition-time validation against the current published and enabled Gateway endpoint; and
- stable managed Gateway endpoint identities and immutable revisions.

Pending work:

- expose the Target-to-endpoint relationship and operator configuration guidance through future
  management and readiness contracts; and
- implement streaming while preserving normalized Hermes session and tool-progress semantics.
