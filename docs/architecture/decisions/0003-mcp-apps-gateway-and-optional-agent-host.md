# ADR 0003: MCP Apps Gateway and Agent Host

- Status: Accepted
- Date: 2026-07-14
- Amended: 2026-07-20

## Context

The project began as a bridge that preserves MCP Apps UI resources for agent runtimes that do not render them natively. Passthrough endpoints now provide a clear one-upstream-to-one-endpoint proxy, but clients must update their MCP configuration whenever they add or remove upstream servers.

A managed product should let an agent configure one stable MCP endpoint while administrators change the available upstream topology in this service. This raises two separate questions:

1. Whether the MCP data plane should aggregate servers explicitly or intercept arbitrary downstream network traffic.
2. Whether the service should also run agents and expose their final text and MCP App interactions to a frontend.

## Decision

### Product identity

The product is an **MCP Apps Gateway**.

Its required core is an MCP-aware gateway that preserves MCP semantics and adds MCP Apps hosting support. It is not a generic TCP forward proxy, HTTP interception proxy, or model-visible administration server.

The product has three planes and two equal product pillars. The Gateway pillar owns the MCP data and management planes. The Agent Host pillar owns agent execution and the enhanced UI event surface. Agent Host activation remains optional for deployments that only need MCP gateway behavior, but the capability is part of the first release rather than a deferred add-on.

| Plane | Responsibility |
| --- | --- |
| MCP data plane | Streamable HTTP/SSE endpoints, MCP session routing, passthrough and aggregate tool/resource forwarding, MCP Apps metadata preservation |
| Management plane | Upstream and endpoint CRUD, policies, health, session inspection, audit events, and deployment configuration |
| Agent Host plane | Agent adapters, run lifecycle, assistant text/events, tool activity, rendered MCP App widgets, and host-owned UI actions |

The Gateway and Agent Host pillars are equal core capabilities. The Agent Host depends on adapters and must not leak agent-specific behavior into the generic gateway runtime.

### Stable aggregate endpoint

Aggregate is the primary publication strategy and the path to a configure-once client experience: an installation may publish a stable endpoint such as `/mcp/default`, which administrators update through the management plane.

Passthrough remains a lower-priority compatibility and diagnostic strategy for:

- Debugging one upstream without aggregate rewriting.
- Compatibility with clients or servers that require original names and resource URIs.
- Operational isolation and diagnosis.
- Agent-specific MCP sets when different agents should receive different upstream combinations.

Deployments may combine both strategies by publishing aggregate endpoints for common toolsets and passthrough endpoints for isolated or compatibility-sensitive servers. Distinct downstream consumers should be assigned endpoint revisions or policies rather than receiving copied aggregate sessions. Supporting multiple consumers with distinct endpoint assignments is a future management capability, not a requirement of the initial aggregate implementation.

Aggregate tools always use a stable server namespace, following the same principle used by clients such as Hermes to distinguish MCP tools from local tools. The canonical shape is:

```text
{server_namespace}__{upstream_tool_name}
```

The public MCP layer may add its own MCP category prefix when required by an agent adapter, but that adapter-specific prefix is not stored as the gateway tool identity. Namespace assignment defaults to a stable upstream slug and may later support an explicit administrator-defined alias.

Names are always namespaced, not only when a collision occurs. Adding a new upstream therefore cannot rename an existing public tool. Aggregate resource URIs include the same binding namespace while preserving the semantics defined below. Prompt aggregation must follow the same collision-safe principle when that MCP capability is implemented.

The first aggregate implementation uses degraded availability. Downstream initialization does not require every upstream to be reachable. Discovery queries enabled bindings concurrently and returns deterministic results from healthy upstreams while recording binding-scoped failures; discovery fails only when every relevant binding fails. A targeted tool or resource operation depends only on its routed upstream. Failed connections remain retryable for the lifetime of the bridge session.

### Aggregate resource URI routing

Ordinary resource URIs preserve their model-visible semantics and add only the binding namespace required for aggregate routing. The public form prefixes the original URI scheme:

```text
{namespace}+{original_uri}
```

For example, `file:///repo/readme.md` becomes `docs+file:///repo/readme.md`, and `https://example.test/manual` becomes `docs+https://example.test/manual`. The original URI remains readable and is not encoded with Base64, UUIDs, revision identifiers, or gateway-specific path segments. Namespaces use lowercase letters, digits, and hyphens, begin with a lowercase letter, and are always applied on aggregate endpoints so adding a binding cannot rename an existing public resource.

MCP Apps resources retain the required `ui://` scheme and use a host-facing route token:

```text
ui://{namespace}/{opaque_token}
```

The token is not model routing metadata and does not encode a binding or revision. The bridge session keeps an exact route table from each public URI to its binding revision and original upstream URI. Only URIs registered through discovery, tool metadata, or protocol resource content can be read; the gateway does not trust a decodable public token as routing authority.

URI rewriting is limited to protocol-defined URI locations: resource descriptors and read results, MCP Apps tool metadata, `ResourceLink.uri`, and `EmbeddedResource.resource.uri`. Arbitrary text, structured content, and unrelated metadata are not recursively scanned for URI-like strings. Resource templates follow the same namespace rule when template support is added to the MCP surface.

### Topology consistency

Each new bridge session captures an immutable endpoint topology revision containing its bindings, namespaces, and relevant policy. Each binding references an immutable upstream revision so later changes to transport configuration cannot affect a lazy connection created by an existing session. Administrative changes create new revisions and affect new sessions only. Existing sessions continue with their captured revision until they close.

The first release stores normalized immutable endpoint revisions, upstream revisions, and revision bindings in the relational database. A bridge session references exactly one endpoint revision. Session creation materializes that revision into a process-local routing plan; MCP method dispatch does not query persistence for every tool or resource call.

Domain and MCP modules access topology through behavior-oriented async ports. They do not import SQLAlchemy models, sessions, or relational query concepts. The initial adapter uses SQLAlchemy, while a future graph-backed adapter may implement the same topology contracts if multi-tenant relationship and impact-analysis requirements justify a graph database. A graph database is not required by the first release.

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

Final text requires the Agent Host plane to own the agent run through an integration boundary. The first-release public interface implements the broadly supported OpenAI-compatible core:

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

The current `agent_adapters/` package name and layout are provisional. The durable requirement is an isolated integration boundary between the generic gateway and an independently deployed agent runtime. The first integration uses HTTP and SSE. A generic OpenAI-compatible adapter contains only standard behavior; a separate Hermes HTTP adapter owns Hermes-specific endpoints, event types, and capabilities even when it reuses the common OpenAI request surface.

Hermes ACP is a possible future local-process adapter for an Electron or editor integration. ACP uses JSON-RPC over stdio and must remain separate from the HTTP adapter contracts. It is not part of the first release and does not replace the provider-neutral internal run/event model.

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
- Ordinary aggregate resource URIs retain the original scheme, path, query, and fragment semantics with only a namespace prefix.
- MCP Apps UI routing remains host-facing under `ui://` and does not expose binding or revision identifiers.
- Existing sessions are insulated from administrative topology changes.
- Passthrough remains available for compatibility and diagnosis but does not lead aggregate delivery.
- Final assistant text is available only when the service runs the agent through an adapter.
- The management API, MCP API, and Agent Run API have distinct authentication and authorization surfaces.

## Implementation Sequence

1. Complete SQLite persistence and management-domain CRUD foundations.
2. Add normalized endpoint and upstream revisions and capture one endpoint revision per bridge session.
3. Implement aggregate tool discovery and call routing with stable server namespaces.
4. Implement reversible aggregate resource routing and preserve MCP Apps metadata.
5. Design the provider-neutral internal Run/Event contract and expose the OpenAI-compatible core through an independently deployed Hermes HTTP proof of concept.
6. Separate generic OpenAI-compatible behavior from Hermes-specific HTTP capabilities.
7. Perform an architecture and terminology review before freezing public backend contracts and coupling the first-party frontend to them.
8. Implement the first-party Agent UI and minimal management surface and validate the `mcp-ui` renderer against tool and resource events.
9. Add list-changed notification behavior for new sessions and supported clients without mutating captured revisions.

## Deferred Decisions

### Agent runtime integration

The first integration boundary is HTTP/SSE to an independently deployed Hermes runtime. The remaining decision is the exact provider-neutral run/event contract needed for streaming, cancellation, resume, approval, tool events, and MCP App UI actions. Standard OpenAI-compatible behavior and Hermes-specific behavior must remain separate adapters, and all agent-specific behavior must remain outside the generic MCP gateway modules.

### Authentication boundaries

The management API can modify servers and credentials, MCP clients can invoke powerful tools, and Agent Host users can start agent runs. These are different trust levels and may require separate tokens, scopes, or identities. Authentication is deferred until the corresponding public APIs are designed, but one shared unrestricted credential must not become an accidental permanent contract.
