import { useBridgeSession } from "./hooks/useBridgeSession";

function formatEventLabel(kind: string) {
  return kind.split(".").join(" / ");
}

export function App() {
  const { snapshot, latestEvents, latestResource, connectionState, error } = useBridgeSession();

  return (
    <main className="shell">
      <header className="shell__header">
        <div>
          <p className="eyebrow">MCP Apps Bridge Host</p>
          <h1>mcpapps-bridge</h1>
        </div>
        <div className="status-group">
          <p className="status">Session: {snapshot.session_id}</p>
          <p className={`status status--${connectionState}`}>Stream: {connectionState}</p>
        </div>
      </header>

      <section className="layout">
        <article className="panel">
          <h2>Transcript</h2>
          <p className="panel-copy">
            Transcript rendering has not been connected yet. The backend event stream is live,
            so this surface is ready for user messages, model output, and streaming deltas.
          </p>
          <dl className="stats-list">
            <div>
              <dt>Session status</dt>
              <dd>{snapshot.status}</dd>
            </div>
            <div>
              <dt>Tracked events</dt>
              <dd>{snapshot.event_count}</dd>
            </div>
            <div>
              <dt>Last error</dt>
              <dd>{snapshot.last_error ?? error ?? "none"}</dd>
            </div>
          </dl>
        </article>

        <article className="panel">
          <h2>Bridge Activity</h2>
          <ul className="event-list">
            {latestEvents.length === 0 ? (
              <li className="event-list__empty">No bridge events have been observed yet.</li>
            ) : (
              latestEvents.map((event) => (
                <li className="event-card" key={event.event_id}>
                  <div className="event-card__header">
                    <strong>{formatEventLabel(event.kind)}</strong>
                    <span>{new Date(event.created_at).toLocaleTimeString()}</span>
                  </div>
                  <p className="event-card__body">
                    {event.tool?.name ?? event.call?.tool_name ?? event.resource?.uri ?? event.message ?? "No event details"}
                  </p>
                </li>
              ))
            )}
          </ul>
        </article>

        <article className="panel panel--app">
          <h2>MCP App Surface</h2>
          <p className="panel-copy">
            The host runtime is already discovering tools and loading UI resources. The next step
            is wiring this surface into `@mcp-ui/client`.
          </p>
          <div className="resource-summary">
            <p>
              <strong>Discovered tools:</strong> {snapshot.discovered_tools.length}
            </p>
            <p>
              <strong>Loaded resources:</strong> {snapshot.loaded_resources.length}
            </p>
          </div>
          {latestResource ? (
            <div className="resource-preview">
              <p className="resource-preview__title">Latest resource</p>
              <p>{latestResource.uri}</p>
              <p>{latestResource.mime_type}</p>
              <pre>{latestResource.text ?? "Binary resource payload"}</pre>
            </div>
          ) : (
            <p className="event-list__empty">No MCP App resource has been loaded yet.</p>
          )}
        </article>
      </section>
    </main>
  );
}
