# ADR 0005: Upstream Transport Task Ownership

- Status: Accepted
- Date: 2026-07-24

## Context

The MCP Python SDK implements client sessions and streamable HTTP transports with AnyIO task
groups and cancel scopes. AnyIO context managers that enter cancel scopes must exit in the same
task and in last-in, first-out order.

Aggregate discovery originally created an `UpstreamRuntime` connection inside a temporary
per-binding task and kept the SDK contexts alive after that task returned. Discovery reached the
real server and received tools, but AnyIO rejected the remaining cancel-scope stack when the task
exited. Later cleanup attempted to close the same contexts from another task and failed again.
The resulting protocol symptom was an empty tool list followed by synthesized UI resources.

This is a lifecycle ownership defect, not an SSE content-negotiation defect. A direct client using
the same SDK successfully performs later MCP requests after a bounded SSE initialization response.

## Decision

Each bridge-session binding has one persistent upstream worker task. `BridgeManager` provides its
process-lifecycle task group as the execution host for these workers. `UpstreamRuntime` owns a
typed command channel to its worker and routes all upstream operations through that channel:

- connect and initialize;
- tool and resource discovery;
- tool calls and resource reads;
- disconnect, reconnect, and final shutdown.

The worker enters every MCP SDK transport and `ClientSession` context, executes every client
operation, and exits every context in that same task. Router discovery tasks may remain concurrent,
but they submit commands and never directly own SDK lifecycle contexts.

Session shutdown sends an explicit shutdown command and waits until the worker has completed
same-task transport cleanup. The manager task group remains the structured-concurrency parent and
is closed only after all bridge sessions have stopped their workers.

Passthrough and aggregate routers use the same worker-backed `UpstreamRuntime`. Transport task
ownership is therefore independent of publication mode and transport type.

## Consequences

- Long-lived SDK cancel scopes never outlive or move between their owner tasks.
- Aggregate discovery retains per-binding concurrency while each binding serializes operations on
  its stateful MCP session.
- Failed bindings can disconnect and reconnect through the same worker without changing task
  ownership.
- One slow request blocks later requests for the same upstream session, matching the stateful
  session's serialization boundary. Different aggregate bindings remain concurrent.
- Worker commands that have been accepted may complete even if the submitting downstream request
  is cancelled. Later work may add operation-level cancellation without transferring SDK context
  ownership.
- The runtime requires a manager-owned task group before upstream operations can begin.

## Verification

The regression suite records the task identity of connect, protocol operations, reconnect, and
close while callers run in different temporary tasks. Every underlying client operation must use
one owner task.

The v0.1 protocol check also exercises a real streamable HTTP upstream through an aggregate
gateway session and requires successful initialize, tools/list, resources/list, resources/read,
and clean process shutdown.

## Rejected Alternatives

### Catch cancellation with `BaseException`

The original failure occurred after the discovery coroutine returned, outside its `try` block.
Swallowing cancellation would not repair the invalid cancel-scope stack and would violate
structured concurrency.

### Move discovery into router startup

This would avoid one temporary task during initial discovery but would not cover lazy reconnects
or calls made from later downstream request tasks. Lifecycle ownership must be explicit for every
operation.

### Open a new MCP session for every request

MCP sessions carry negotiated capabilities, protocol version, notifications, and transport state.
Reconnecting per method would discard those semantics and add unnecessary latency.
