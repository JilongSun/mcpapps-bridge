# ADR 0015: Agent Host Runs and MCP Apps Endpoint Composition

- Status: Accepted
- Date: 2026-09-21
- Amends: ADR 0003, ADR 0010, ADR 0011, and ADR 0012

## Context

Mabrid was designed around three application contexts with different sources of truth:

- the Gateway preserves and observes MCP protocol activity;
- the Agent Host invokes an independently deployed agent runtime and owns user-facing runs; and
- the MCP Apps context correlates tool activity, application resources, widget instances, and
  host-owned actions.

The first Agent Host slice currently normalizes text from Hermes through OpenAI Chat Completions.
It does not need to understand Hermes's internal agent loop to observe MCP Apps behavior. Hermes
calls the stable Gateway endpoint configured for its Agent Target, and the Gateway already observes
tool descriptors, tool calls, complete MCP tool results, and application-resource reads.

ADR 0011 described the endpoint assignment as non-exclusive product intent and deferred proven
run-to-Gateway correlation. That is too weak for the first-party MCP Apps workflow. If unrelated
targets or clients share an assigned endpoint, endpoint identity cannot determine which active
Agent Host run owns a Gateway tool operation. The v0.1 topology is deliberately narrower and can
make that ownership unambiguous without adding provider-specific headers or depending on Hermes
tool-progress events.

The current bridge also preloads a tool's UI resource after a successful call and retains resource
contents in a process-local cache. Cache invalidation, freshness, and retention are separate design
problems. They should not enter the first release merely to avoid one resource read per UI-producing
tool call.

Agent frameworks such as OpenAI Agents SDK and LangChain Core provide their own message, runner,
tool, MCP, session, and event abstractions. Mabrid hosts an already-running external agent rather
than implementing a second agent loop. Adopting either framework as the Agent Host domain would
duplicate runtime ownership and couple provider-neutral contracts to one orchestration library.

## Decision

### Optional Host and composed MCP Apps capability

The Gateway remains independently deployable. The Agent Host is an optional deployment capability.
When the Agent Host is enabled, first-party MCP Apps hosting is an optional composed capability of
that Host surface.

MCP Apps remains a distinct application context even though users experience it through the Host.
The contexts retain these responsibilities:

- bridge core preserves MCP Apps metadata, routes `ui://` resources, and emits typed protocol
  observations;
- Gateway application services own endpoint sessions and project protocol observations;
- Agent Host owns Target invocation, run lifecycle, assistant output, and runtime ports;
- MCP Apps owns widget instances, application-resource lifecycle, host-visible interaction state,
  and host actions; and
- server composition wires the optional workflow without introducing concrete cross-context
  imports.

The first-party workflow is:

```text
Agent Host run
    -> assigned Gateway endpoint
    -> observed MCP tool operation
    -> fresh MCP App resource read
    -> MCP Apps widget instance
    -> host action or follow-up input
    -> later Agent Host run
```

The Gateway does not require the Agent Host to preserve MCP Apps protocol behavior. The Agent Host
can also run without enabling the first-party MCP Apps workflow.

### Run semantics

An **Agent Run** is one bounded execution of an Agent Target in response to one admitted input. It
starts before the outbound runtime request and reaches exactly one terminal state after runtime
output and all Gateway operations already attributed to it have settled.

A Run is distinct from:

- an Agent Target, which is stable configured identity;
- a conversation, which may contain multiple user turns and Runs;
- a remote runtime process or provider session;
- a Gateway bridge session, which is an MCP transport lifecycle and may span multiple Runs; and
- a tool operation or widget instance, of which one Run may contain many.

The v0.1 lifecycle is `started` followed by `completed`, `failed`, or `cancelled`. Assistant text,
tool activity, resource activity, and widget activity are ordered events within that lifecycle.
Terminal completion is not inferred from the last visible text token. The Host keeps the Run in a
settling state until attributed Gateway operations have completed or failed, then emits the
terminal event.

The Agent Host owns the Run identifier. Provider run, response, and session identifiers are
optional integration metadata and never replace it. OpenAI-compatible request identifiers are
inbound adapter representations of the same Mabrid Run.

For v0.1, each Target admits at most one active Run. A second invocation is rejected while the
first Run is active or settling. Multi-run concurrency, queuing, and scheduling require a later
decision.

### Exclusive Target-to-endpoint assignment

Each enabled Agent Target has exactly one assigned Gateway endpoint, and one Gateway endpoint may
be assigned to at most one Agent Target. The assignment is logical ownership for Agent Host
composition, not merely display metadata.

An assigned endpoint is dedicated to its Target's runtime traffic while the composed MCP Apps Host
workflow is enabled. Other MCP clients must use a different endpoint. v0.1 validates assignment at
composition but does not add network authentication that proves the caller is the configured
runtime; authorization and caller-bound enforcement remain separate security work.

The combination of exclusive endpoint ownership and one active Run gives a deterministic
correlation path:

```text
Gateway endpoint -> Agent Target -> active Agent Run
```

The Host registers the active Run before invoking the runtime. When the Gateway observes
`ToolCallStarted`, composition resolves the bridge session's endpoint and permanently records the
resulting `run_id` against that event's `session_key` and `operation_key`. Completion and UI
resource activity use that recorded operation attribution rather than consulting whichever Run is
active later.

Provider-specific run correlation is not required for this v0.1 workflow. Hermes session headers,
Hermes Runs, custom tool-progress events, and runtime-internal tool identifiers may improve later
integrations but are not the source of truth for MCP Apps correlation.

### Observation composition and event ownership

Bridge core continues to emit provider-independent `BridgeObservation` values through one observer
port. The application layer supplies a composite observer that sends the same observation to:

- the existing Gateway inspection projector; and
- an optional MCP Apps lifecycle projector when the composed Host capability is enabled.

Bridge core does not import Agent Host or MCP Apps services. The Gateway inspection projector does
not become a general event bus. Composition owns fan-out and supplies only narrow ports required to
resolve endpoint ownership, active Runs, and MCP Apps lifecycle actions.

`ToolCallStarted.operation_key` is the causation identity for one tool operation. An automatic UI
resource read caused by that call must carry the same operation identity in its observation. This
allows the MCP Apps context to construct a widget instance from:

- `run_id`;
- `target_id`;
- Gateway `session_key`;
- tool `operation_key` and tool name;
- the complete MCP tool result;
- the application resource URI; and
- the freshly read application resource contents.

Assistant text events remain Agent Host events. Tool and resource facts remain Gateway events.
Widget lifecycle and host-action events remain MCP Apps events. A Host-facing stream may merge
these event families into one ordered presentation contract, but it does not move their ownership
into one domain union or expose provider wire events directly.

### Fresh application-resource reads

For every completed tool call whose published descriptor has an MCP App resource URI, the Gateway
performs one resource read for that tool operation. It does not reuse resource contents loaded by a
previous operation, even when the URI is unchanged.

The existing preload behavior becomes an explicit post-tool-call application-resource load. A
resource-read failure does not rewrite a successful MCP tool result as a failed tool call. It emits
an attributable resource or widget failure so the Host can present the tool result without a
widget.

v0.1 does not add optional caching, cache invalidation, freshness policy, TTL, or stale fallback.
Existing resource-content and lazy remote-model optimization caches are removed or bypassed as
their owning paths are implemented. Immutable endpoint revisions, session route tables, published
tool descriptors, active-Run attribution, and persisted lifecycle records are authoritative
runtime state rather than optimization caches.

Any future cache must be introduced through a dedicated decision that defines ownership,
invalidation, consistency, bounds, and observability.

### Keep agent frameworks outside provider-neutral contracts

Mabrid does not adopt OpenAI Agents SDK or LangChain Core as a v0.1 application dependency.

OpenAI Agents SDK may inform the distinction between raw provider events, semantic run-item events,
and lifecycle events. Its `Runner`, session memory, MCP client, tool execution, handoffs, and
tracing do not replace Mabrid services because those features implement an agent loop that the
external Agent Runtime already owns.

LangChain message and runnable types do not enter `AgentMessage`, Run commands, events, or runtime
ports. The existing small Pydantic contracts remain Mabrid-owned. A future OpenAI Agents or
LangChain integration may implement the `AgentRuntime` port and translate at that adapter boundary
without changing the provider-neutral application model.

The official OpenAI Python SDK remains appropriate for OpenAI-compatible HTTP wire validation and
the Hermes HTTP client. Its types remain outside application contracts.

## Consequences

- Mabrid can host MCP Apps without depending on whether an external runtime understands MCP Apps
  or exposes its internal tool loop.
- Endpoint assignment becomes behaviorally meaningful and provides deterministic v0.1 correlation.
- The single-active-Run constraint limits concurrency but avoids provider-specific correlation and
  premature scheduling machinery.
- Gateway protocol facts, Agent Host lifecycle, and MCP Apps product state retain separate owners.
- Each UI-producing tool call performs an additional resource read, favoring correctness and simple
  semantics over optimization.
- Direct use of an Agent Target's assigned endpoint by unrelated clients violates the v0.1
  composition contract even though transport-level access control does not yet enforce it.
- Provider integrations remain replaceable because no orchestration framework owns the application
  contracts.

## Explicitly Deferred

- Multiple Agent Targets and multiple concurrent Runs per Target.
- Shared endpoints, run queues, scheduling, and concurrent correlation.
- Network enforcement of endpoint ownership and caller identity.
- Resource, tool-list, model-discovery, or event caching and invalidation policy.
- OpenAI Responses and Hermes Runs runtime interfaces.
- Provider-specific session continuity, detached runs, approvals, steering, and resume.
- OpenAI Agents SDK and LangChain runtime integrations.
- Cross-runtime evaluation, comparison, and enterprise testing workflows.

## Implementation Sequence

1. Extend endpoint assignment validation and runtime coordination with exclusive ownership and one
   active Run per Target.
2. Add an application-level composite bridge observer and operation-to-Run attribution port.
3. Replace UI resource preloading with one attributable, uncached resource read per UI-producing
   tool call.
4. Add MCP Apps lifecycle contracts and project correlated tool results and resource reads into
   widget events.
5. Extend the Host-facing event stream to merge assistant and MCP Apps presentation events without
   changing domain ownership.
6. Implement true streaming through the selected Hermes Chat Completions integration and the
   OpenAI-compatible inbound adapter.
7. Validate the complete workflow with controlled Gateway, runtime, MCP server, and MCP App
   fixtures.

## Implementation Status

As of 2026-09-22, this decision is **Partial**.

Implemented foundations include the single configured Target and endpoint assignment,
provider-neutral Run identity and ordered text events, typed Gateway tool and resource
observations, and preserved MCP Apps metadata. An application coordinator now rejects duplicate
Target identities and endpoint ownership, admits at most one active Run per Target, and releases
active ownership on terminal completion, failure, or event stream cancellation. Gateway sessions
compose their inspection projector with an optional Agent Host observer that permanently
attributes each observed tool operation to the active Run at `ToolCallStarted`.

Every UI-producing tool call now performs a fresh application-resource read carrying the same
operation identity. Resource contents are not cached, and a failed automatic read emits an
attributable error without replacing the successful tool result. The MCP Apps application context
now projects correlated tool results and application resources into renderer-neutral widget
creation or failure events. A Host presentation stream now wraps Agent Host and MCP Apps domain
events without changing their ownership, waits for attributed widget operations to settle before
the Run terminal event, and is composed with or without the optional MCP Apps workflow.
