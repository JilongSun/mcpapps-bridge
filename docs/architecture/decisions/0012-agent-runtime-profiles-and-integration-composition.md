# ADR 0012: Agent Runtime Profiles and Integration Composition

- Status: Accepted
- Date: 2026-08-25
- Amends: ADR 0010 and ADR 0011

## Context

ADR 0011 established one Agent Target for v0.1 and selected Hermes over non-streaming OpenAI Chat
Completions as its first runtime integration. The initial implementation still represented the
integration as the string `hermes-http`. That string combined several independent concerns:

- the external runtime product, Hermes;
- HTTP as the transport;
- OpenAI Chat Completions as the API interface; and
- the behavior currently implemented by the local adapter.

Hermes exposes several API families through the same HTTP process: Chat Completions, Responses,
detached Runs, persisted Sessions, and runtime-specific control operations. Its capability endpoint
also advertises streaming, tool progress, approvals, steering, stopping, and session continuity.
The local integration does not yet implement all of those behaviors. Treating remote support as a
Gateway capability would therefore overstate what the Agent Host can provide to an API or
first-party frontend.

The codebase must also admit additional runtime integration types without introducing multiple
simultaneously active targets, a runtime registry, or model routing before the product needs them.

## Decision

### Separate target, integration, interface, and capability

The Agent Host uses four distinct concepts:

- **Agent Target** is the stable product and management identity advertised through the
  OpenAI-compatible model representation. It retains the Gateway endpoint assignment.
- **Runtime integration** identifies the external runtime family, initially `hermes`.
- **Runtime interface** identifies the selected API family used by the integration, initially
  `openai-chat-completions`.
- **Agent capability** identifies provider-neutral behavior that the local Agent Host can actually
  deliver through the selected implementation.

An immutable `AgentRuntimeProfile` combines the integration kind, selected interface, and static
implemented capabilities. The configured Agent Target captures that profile. Composition fails if
the runtime instance reports a different profile from its Target.

The initial Hermes Chat Completions runtime reports only:

- text generation; and
- token usage.

It does not report streaming, session continuity, tool activity, approvals, detached runs,
steering, or stopping until the local integration and provider-neutral contracts implement those
behaviors.

### Effective capabilities are conservative

A remote runtime capability response is discovery evidence, not the product's effective
capability contract. The eventual effective set is the intersection of:

1. behavior implemented by the selected local runtime integration;
2. behavior advertised or verified by the configured remote runtime; and
3. behavior enabled by deployment policy.

The first implementation uses only the static local implementation profile. Dynamic probing of
Hermes `/v1/capabilities`, readiness state, and drift reporting are deferred. Startup therefore
does not require Hermes to be reachable.

MCP Apps rendering is not an Agent Runtime capability. It is a composed product capability that
requires provider-neutral tool and resource events, Gateway session correlation, the MCP Apps
application context, and a frontend renderer.

### Keep runtime ports behavior-oriented

`AgentRuntime` is the narrow application port used by `AgentHostService`. It exposes:

- an immutable runtime profile; and
- the provider-neutral run event stream.

`ManagedAgentRuntime` extends that port with deployment lifecycle cleanup. The server composition
root owns the managed lifecycle; `AgentHostService` does not.

Future control behavior such as approve, steer, stop, resume, or detached-run lookup will use
narrow optional ports when their application commands and events exist. The base runtime port will
not accumulate methods that most integrations implement only by raising unsupported-operation
errors.

### Allow multiple integration types without multiple active targets

The service distribution may contain multiple isolated runtime implementations. The deployable
server owns typed runtime configuration and an explicit builder that selects one implementation.
The v0.1 process still constructs exactly one Agent Target and one managed runtime instance.

Configuration separates the target from its runtime selection:

```yaml
agentHost:
  enabled: true
  targetId: hermes-agent
  endpointSlug: test-endpoint
  runtime:
    integration: hermes
    interface: openai-chat-completions
    baseUrl: http://127.0.0.1:8642/v1
    apiKeyEnv: API_SERVER_KEY
```

Runtime-specific configuration variants may later form a discriminated union keyed by
`integration`. Adding another integration changes the configuration union and server builder, not
the provider-neutral Agent Host service. Adding another interface to the same integration changes
that runtime's configuration and builder branch without inventing compound identifiers such as
`hermes-responses-http`.

A target registry, simultaneous runtime instances, strict model-to-target routing, load balancing,
and per-run interface selection remain deferred until a second active Target is required.

## Consequences

- Agent Target identity no longer conflates runtime vendor, transport, API family, and behavior.
- Frontends and management APIs can eventually consume a conservative provider-neutral capability
  set without depending on Hermes-specific fields.
- The server can add runtime integration types through explicit configuration and composition while
  the service continues to depend on one narrow port.
- Runtime/Target mismatches fail during composition rather than producing incorrect behavior during
  a run.
- Some remote Hermes features remain intentionally hidden until corresponding application commands,
  events, and tests exist.
- Runtime-specific configuration is nested and is not backward compatible with the provisional
  flat `integration: hermes-http` configuration.

## Rejected Alternatives

### A universal adapter base class

A base class combining text generation, streaming, sessions, tools, approvals, steering, and
lifecycle would force unsupported methods onto integrations and couple unrelated API families.
Small protocols and composed optional ports preserve clearer contracts.

### Mirror the remote capability document

Passing Hermes feature flags directly to the frontend would claim support for behaviors the local
adapter does not normalize or expose. Remote capabilities remain provider input to a future
effective-capability calculation.

### Build a multi-target registry now

Multiple implementation types do not require multiple active runtime instances. A registry would
also require target persistence, strict model routing, lifecycle ownership, readiness aggregation,
and selection policy that v0.1 does not yet need.

## Explicitly Deferred

- Dynamic remote capability probing and readiness state.
- Provider-neutral streaming, tool activity, approvals, stop, steer, and detached-run contracts.
- Optional run-control ports for those behaviors.
- Responses and Hermes Runs runtime implementations.
- Multiple simultaneous Agent Targets and target registries.
- Product-level MCP Apps capability composition and run-to-Gateway-session correlation.

## Implementation Status

As of 2026-08-25, this decision is **Partial**.

Implemented:

- runtime interface and provider-neutral capability enums;
- immutable runtime profiles captured by Agent Targets;
- profile compatibility validation in `AgentHostService`;
- narrow application and managed-lifecycle runtime ports;
- a static Hermes Chat Completions profile;
- nested runtime configuration; and
- a server-owned runtime builder that composes one target and runtime.

Pending:

- additional runtime integration or interface implementations;
- effective capability exposure through management and readiness APIs; and
- dynamic remote capability verification.
