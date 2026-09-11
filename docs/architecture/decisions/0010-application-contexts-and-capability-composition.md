# ADR 0010: Application Contexts and Capability Composition

- Status: Accepted; amended by ADR 0011, ADR 0012, ADR 0013, and ADR 0014
- Date: 2026-08-21
- Amends: ADR 0003 and ADR 0006

ADR 0011 defines the v0.1 single Agent Target and its declared Gateway endpoint assignment, and it
moves reusable outbound Agent Runtime integrations from the deployment server into an isolated
area of the service distribution.
ADR 0012 separates runtime integration, API interface, and effective capabilities while retaining
one configured Agent Target and one runtime instance.
ADR 0013 implements the context-oriented `mabrid.application` structure and removes the redundant
Gateway journal DTO layer while preserving the bounded contexts accepted here.
ADR 0014 retains topology administration as a Gateway application responsibility but limits v0.1
to read-only topology and operational inspection APIs.

## Context

ADR 0006 established a reusable bridge core, one application-service package, and a deployable
server. The application package now owns or anticipates several responsibilities that are related
through the product but have different data, lifecycle, and dependency semantics:

- coordinating Gateway sessions and managed topology;
- retaining detailed session diagnostics;
- deriving operational usage insights such as upstream and tool call frequency;
- correlating MCP Apps resources with tool activity and handling host-owned UI actions; and
- running agents through provider-neutral contracts and concrete provider adapters.

Treating all of these responsibilities as one generic management or host service would reproduce
the coupling that ADR 0006 removed from the protocol layer. Splitting each responsibility into a
separate Python distribution now would instead add package facades and dependency management
before any context needs independent release or deployment.

MCP Apps and Agent Host are closely related in the first-party experience: an agent run can produce
a tool result that references a widget, and a widget action can send follow-up input to that run.
They are not the same capability. Agent runs must remain usable without a rendered widget, and MCP
Apps resources must remain bridgeable and inspectable without enabling the product's Agent Host.

The product also needs a distinction between desired configuration and observed operation.
Topology administration changes what a later Gateway process should run, while diagnostics and
usage insights describe what previous or current calls actually did.

## Decision

### One application package, three bounded contexts

The second architecture layer remains one internal `gateway-service` distribution for v0.1. It is
organized conceptually into three bounded contexts.

#### Gateway application context

The Gateway context owns:

- **Runtime coordination:** selecting a captured endpoint revision, opening and closing bridge
  sessions, transport-session correlation, and application lifecycle state.
- **Topology administration:** managed upstreams, endpoints, bindings, policies, immutable
  revision publication, validation, and the restart-applied behavior defined by ADR 0008.
- **Session diagnostics:** detailed session events, snapshots, availability, errors, tool activity,
  and resources needed to inspect and debug a particular session.
- **Usage insights:** minimized operational facts and aggregate queries such as call counts,
  failures, latency, and hot upstreams or tools.

Topology administration and operational observation are separate application responsibilities.
They may share stable endpoint, revision, upstream, and session identifiers, but they do not share
command models or pretend that statistics are configuration CRUD.

Session diagnostics and usage insights are also separate projections. Diagnostics may retain
detailed payloads for a specific session. Usage facts contain only the dimensions and measurements
needed for aggregate queries and must not copy tool arguments, tool results, MCP App payloads, or
credentials by default.

Usage projection consumes typed bridge observations. Failure to record an optional usage fact must
not fail, delay indefinitely, or change the result of an MCP operation. Stronger delivery such as
an outbox, external metrics backend, or billing-grade accounting requires a later decision.

#### MCP Apps application context

The MCP Apps context owns product host behavior above protocol bridging:

- application-resource lifecycle and correlation with tool activity;
- widget instances and host-visible interaction state;
- validation and dispatch of host-owned actions;
- links between app activity, Gateway sessions, and Agent Host runs when those contexts are
  composed; and
- frontend-facing application events that are independent of a concrete renderer.

Bridge-core continues to own MCP Apps protocol metadata preservation, `ui://` routing, and exact
resource-route authorization. The application context does not duplicate those mechanisms. It
begins where the product stores, renders, correlates, or acts on a bridged application resource.

MCP Apps host workflows depend on narrow ports and provider-neutral events, not on a concrete
agent adapter or frontend library. Rendering through `@mcp-ui/client` remains a frontend adapter
concern.

#### Agent Host application context

The Agent Host context owns:

- provider-neutral run, message, content, tool-activity, and lifecycle contracts;
- starting, streaming, cancelling, and completing runs;
- conversation and run event publication;
- provider-neutral agent adapter ports; and
- policies for selecting configured adapters, models, and Gateway endpoints.

Concrete OpenAI-compatible and Hermes HTTP/SSE adapters remain in the deployable server package.
Hermes-specific events and capabilities do not enter the provider-neutral context or the Gateway
context.

### Composition without strong binding

The contexts integrate through explicit application ports, stable identifiers, and typed events.
They do not import each other's concrete services or persistence adapters.

The first-party MCP Apps-capable agent workflow composes all three contexts:

```text
Agent Host run
    -> Gateway tool activity
    -> MCP Apps resource lifecycle
    -> frontend widget
    -> host-owned action
    -> Agent Host run command
```

This workflow-level dependency does not make Agent Host and MCP Apps one bounded context:

- Agent Host can run and stream text or ordinary tool calls without MCP Apps host workflows.
- Gateway can preserve and expose MCP Apps resources to downstream clients without Agent Host.
- MCP Apps resources can be inspected or rendered from Gateway activity without an active
  first-party agent run.
- Actions that require conversational follow-up are available only when composition supplies an
  Agent Host action port and a valid run correlation.

The server composition root wires these optional integrations. Neither context discovers another
through global state or imports its concrete implementation.

### Capabilities and deployment configuration

The product has one Gateway implementation rather than separate `BasicGateway` and
`EnhancedGateway` classes. User-facing presets may group features, but runtime assembly expands
them into explicit capabilities.

- Gateway data-plane routing is foundational.
- Topology administration is a passive application service and follows ADR 0008.
- Detailed session diagnostics may be configured by retention or detail policy.
- Usage insights are optional.
- Agent Host is optional at deployment time but remains a required product capability for the
  v0.1 release under ADR 0004.
- MCP Apps protocol preservation is part of the Gateway; first-party host workflows are composed
  when a host surface requires them.

Process-level feature selection belongs to server YAML or environment configuration because it
controls which services, sinks, persistence adapters, background lifecycles, and routes are
assembled. The API exposes effective capabilities so the frontend can render only supported
workflows. The frontend does not start or stop backend contexts dynamically.

Capability changes that require different process assembly take effect after restart. This does
not introduce live plugin loading or weaken ADR 0008's restart-applied configuration model.

### Module and package evolution

The current flat `mcp_gateway_service` modules may migrate incrementally toward context-oriented
modules or subpackages. No big-bang directory refactor is required by this decision. New behavior
is placed with its owning context, and existing modules move only when a feature change provides a
focused validation path.

A future shape may include:

```text
mcp_gateway_service/
|-- gateway/       # runtime, topology, diagnostics, usage
|-- mcp_apps/      # resource lifecycle and host actions
`-- agent_host/    # runs, events, and provider-neutral ports
```

These are module boundaries inside one distribution. A context becomes a separate package or
service only after independent deployment, reuse, scaling, trust, or dependency requirements
justify the additional boundary.

In the server package, `agent_adapters/` contains concrete provider integrations. The existing
`host/` area owns Web process hosting and must not become the Agent Host application domain merely
because the names overlap.

## Consequences

- The second layer has explicit ownership without multiplying deployable packages.
- Topology commands, diagnostic records, and usage facts can evolve independently while sharing
  stable identity contracts.
- Detailed session inspection is not forced to serve as an analytics database.
- MCP Apps and Agent Host remain independently testable, while the first-party widget workflow can
  compose them without adapter-specific coupling.
- Optional operational features can be omitted from a personal deployment without creating a
  second Gateway implementation.
- Context facades add a small amount of import structure but keep ownership explicit inside one
  application distribution.

## Explicitly Deferred

- Separate Python distributions for each application context.
- Independent network services for Gateway, MCP Apps workflows, and Agent Host.
- Live capability loading or unloading.
- External metrics, tracing, or analytics infrastructure.
- Billing-grade usage accounting and guaranteed analytics delivery.
- A generic event bus introduced only to connect in-process contexts.

## Implementation Status

As of 2026-09-01:

- **Implemented:** `mabrid.application` separates Gateway topology, sessions, inspection, and Agent
  Host contracts; core observations project directly into detailed session events/snapshots; the
  server composes an independently deployed Hermes HTTP adapter.
- **Partial:** MCP Apps resources are preserved and rendered, but the application resource
  lifecycle and host-owned actions are incomplete.
- **Partial:** the Agent Host context has provider-neutral text run commands, ordered application
  events, model discovery, failure normalization, an adapter port, and non-streaming production
  composition. Tool activity, Gateway endpoint and MCP Apps correlation, session continuity,
  streaming, and persistence remain pending.
- **Pending:** topology administration commands, dedicated usage facts and queries, and effective
  capability reporting.
