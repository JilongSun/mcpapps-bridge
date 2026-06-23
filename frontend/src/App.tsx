export function App() {
  return (
    <main className="shell">
      <header className="shell__header">
        <div>
          <p className="eyebrow">MCP Apps Bridge Host</p>
          <h1>mcpfront</h1>
        </div>
        <p className="status">v0.1 scaffold</p>
      </header>

      <section className="layout">
        <article className="panel">
          <h2>Transcript</h2>
          <p>
            This panel will render user messages, model output, and streamed assistant
            deltas.
          </p>
        </article>

        <article className="panel">
          <h2>Bridge Activity</h2>
          <p>
            This panel will show tool calls, MCP resource loading, and bridge diagnostics.
          </p>
        </article>

        <article className="panel panel--app">
          <h2>MCP App Surface</h2>
          <p>
            This panel will host the rendered MCP App widget once the bridge runtime is in
            place.
          </p>
        </article>
      </section>
    </main>
  );
}
