# ADR 0003: MCP Apps Gateway and Optional Agent Host

- Status: Accepted
- Date: 2026-07-14

## Context

The project began as a bridge that preserves MCP Apps UI resources for agent runtimes that do not render them natively. Passthrough endpoints now provide a clear one-upstream-to-one-endpoint proxy, but clients must update their MCP configuration whenever they add or remove upstream servers.

A managed product should let an agent configure one stable MCP endpoint while administrators change the available upstream topology in this service. This raises two separate questions:

1. Whether the MCP data plane should aggregate servers explicitly or intercept arbitrary downstream network traffic.
2. Whether the service should also run agents and expose their final text and MCP App interactions to a frontend.

## Decision

### Product identity

The product is an **MCP Apps Gateway**.

Its required core is an MCP-aware gateway that preserves MCP semantics and adds MCP Apps hosting support. It is not a generic TCP forward proxy, HTTP interception proxy, or model-visible administration server.

The product has three planes:

| Plane | Responsibility |
| --- | --- |
| MCP data plane | Streamable HTTP/SSE endpoints, MCP session routing, passthrough and aggregate tool/resource forwarding, MCP Apps metadata preservation |
| Management plane | Upstream and endpoint CRUD, policies, health, session inspection, audit events, and deployment configuration |
| Optional Agent Host plane | Agent adapters, run lifecycle, assistant text/events, tool activity, rendered MCP App widgets, and host-owned UI actions |

The MCP data and management planes are the core product. The Agent Host plane is optional and depends on adapters; it must not leak agent-specific behavior into the generic gateway runtime.

### Stable aggregate endpoint

Passthrough and aggregate are both first-class publication strategies. Aggregate is the primary path to a configure-once client experience: an installation may publish a stable endpoint such as `/mcp/default`, which administrators update through the management plane.

Passthrough remains first-class for:

- Debugging one upstream without aggregate rewriting.
- Compatibility with clients or servers that require original names and resource URIs.
- Operational isolation and diagnosis.
- Agent-specific MCP sets when different agents should receive different upstream combinations.

Deployments may combine both strategies by publishing aggregate endpoints for common toolsets and passthrough endpoints for isolated or compatibility-sensitive servers. Supporting multiple agents with distinct endpoint assignments is a future management capability, not a requirement of the initial aggregate implementation.

Aggregate tools always use a stable server namespace, following the same principle used by clients such as Hermes to distinguish MCP tools from local tools. The canonical shape is:

```text
{server_namespace}__{upstream_tool_name}
```

The public MCP layer may add its own MCP category prefix when required by an agent adapter, but that adapter-specific prefix is not stored as the gateway tool identity. Namespace assignment defaults to a stable upstream slug and may later support an explicit administrator-defined alias.

Names are always namespaced, not only when a collision occurs. Adding a new upstream therefore cannot rename an existing public tool. Resource URIs use a reversible gateway URI that includes the same binding namespace. Prompt and resource aggregation must follow the same collision-safe principle when those MCP capabilities are implemented.

### Topology consistency

Each new bridge session captures an immutable endpoint topology revision containing its bindings, namespaces, and relevant policy. Administrative changes affect new sessions only. Existing sessions continue with their captured revision until they close.

Live topology mutation for existing sessions is deferred. A future design may use MCP list-changed notifications and explicit client capability checks, but it must not silently change tool routing during an active run.

### No transparent network interception

The gateway does not intercept arbitrary downstream network requests.

- Stdio MCP servers do not use network traffic that an HTTP proxy can intercept.
- HTTPS interception would require explicit proxy configuration or TLS man-in-the-middle certificates.
- A network proxy cannot safely resolve MCP tool-name collisions, resource URI rewriting, initialization capabilities, notifications, or stateful session ownership without becoming an MCP application gateway anyway.
- Interception cannot discover an agent's unrelated local MCP configuration reliably or portably.

Clients still explicitly configure one gateway URL. The configure-once benefit comes from aggregate MCP semantics and managed bindings, not from hidden packet interception.

An ordinary reverse proxy or ingress may terminate TLS and route traffic to the gateway in deployment. It remains infrastructure and does not replace MCP-aware aggregation.

### Agent final output

An MCP server does not receive the agent's final assistant response. MCP traffic only exposes protocol operations sent to the server, such as tool and resource requests. The gateway therefore cannot reliably recover final text by observing MCP calls.

Final text requires the optional Agent Host plane to own the agent run through an integration boundary. The initial public interface implements the broadly supported OpenAI-compatible core:

- `POST /v1/chat/completions`, including non-streaming and SSE streaming responses.
- `POST /v1/responses`, including stored response chains where the selected runtime supports them.
- `GET /v1/models`.
- Liveness and readiness endpoints.

This surface is prioritized because existing frontends such as Open WebUI, LobeChat, LibreChat, and similar projects can use it without a project-specific client. The canonical internal run/event model must still represent:

- User input and run lifecycle.
- Incremental and final assistant text.
- Tool calls and results.
- MCP session and upstream activity.
- MCP App resource/widget events.
- Host-owned UI actions and follow-up input.

The internal event envelope remains provider-neutral, but OpenAI-compatible HTTP contracts are the first public adapter rather than a later compatibility layer. Hermes-specific capabilities such as `/v1/capabilities`, detached runs, run cancellation and approval, session management, jobs, and custom tool-progress events are later enhancements after the common surface works.

The `MCP-UI-Org/mcp-ui` TypeScript SDK provides MCP Apps UI resource helpers, sandboxed `AppRenderer`/`AppFrame` rendering, and UI action handling. It does not provide the Agent Run API. It is the preferred renderer candidate for a future host frontend, whether that frontend is built locally or adapted from an existing OpenAI-compatible project.

The current `agent_adapters/` package name and layout are provisional. The durable requirement is an isolated integration boundary between the generic gateway and an agent runtime; the package may be renamed, split, or replaced after the first OpenAI-compatible proof of concept identifies the correct contract.

### Deployment modes

The same backend package supports two explicit modes:

| Mode | Components |
| --- | --- |
| Gateway | MCP data plane and management plane |
| Gateway + Agent Host | Gateway components plus one or more configured agent adapters and the Run/Event API |

Both modes use one backend service initially. Module boundaries must allow the Agent Host plane to become a separate service if scaling, trust, or provider dependencies require it later.

## Consequences

- A downstream agent can configure one stable aggregate MCP endpoint.
- The service remains protocol-aware and can preserve MCP Apps behavior rather than acting as a byte-forwarding proxy.
- Always-namespaced tool identities remain stable as upstream servers are added.
- Existing sessions are insulated from administrative topology changes.
- Passthrough remains useful and does not become a deprecated implementation detail.
- Final assistant text is available only when the service runs the agent through an adapter.
- The management API, MCP API, and Agent Run API have distinct authentication and authorization surfaces.

## Implementation Sequence

1. Complete SQLite persistence and management-domain CRUD foundations.
2. Add endpoint topology revisions and capture one revision per bridge session.
3. Implement aggregate tool discovery and call routing with stable server namespaces.
4. Implement reversible aggregate resource routing and preserve MCP Apps metadata.
5. Add list-changed notification behavior for new sessions and supported clients without mutating captured revisions.
6. Design the provider-neutral internal Run/Event contract and expose the OpenAI-compatible core with one agent runtime proof of concept.
7. Add Hermes-specific capabilities only after the common OpenAI surface and integration boundary are stable.
8. Validate the `mcp-ui` renderer against tool and resource events before selecting or forking a frontend.

## Deferred Decisions

### Aggregate resource URI encoding

Aggregate resources need a public URI containing the server namespace while still allowing the gateway to reconstruct the original upstream URI exactly. The deferred choice is the concrete encoding, for example a gateway-owned URI scheme with an encoded upstream URI versus a path-and-query form. It will be decided with aggregate resource routing because URI opacity, length, and client compatibility need executable validation.

### Topology revision representation

Active sessions must keep the endpoint bindings they started with. The deferred choice is how to persist that frozen topology: normalized immutable revision and binding tables, or a canonical JSON snapshot attached to each session. Normalized revisions support querying and reuse; snapshots are simpler and preserve an exact historical view. This will be decided before aggregate session creation is implemented.

### Agent runtime integration

The common public API is OpenAI-compatible, but the internal integration with an agent runtime is not fixed. The first proof of concept will determine whether a renamed adapter protocol, a subprocess/HTTP client, or a dedicated Agent Host service best handles streaming, cancellation, resume, approval, and tool events. Hermes-specific behavior must remain outside the generic MCP gateway modules.

### Authentication boundaries

The management API can modify servers and credentials, MCP clients can invoke powerful tools, and Agent Host users can start agent runs. These are different trust levels and may require separate tokens, scopes, or identities. Authentication is deferred until the corresponding public APIs are designed, but one shared unrestricted credential must not become an accidental permanent contract.
