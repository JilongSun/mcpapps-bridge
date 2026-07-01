import { useEffect, useMemo, useRef, useState } from "react";

import type { BridgeSessionSnapshot, EventBatch, SessionEvent } from "../types";

type ConnectionState = "connecting" | "open" | "closed" | "error";

const EMPTY_SNAPSHOT: BridgeSessionSnapshot = {
  session_id: "unknown-session",
  status: "starting",
  discovered_tools: [],
  active_tool_calls: [],
  loaded_resources: [],
  last_error: null,
  event_count: 0,
};

function buildWebSocketUrl(path: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
}

export function useBridgeSession() {
  const [snapshot, setSnapshot] = useState<BridgeSessionSnapshot>(EMPTY_SNAPSHOT);
  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [error, setError] = useState<string | null>(null);
  const afterRef = useRef(0);

  async function refreshSnapshot(signal?: AbortSignal) {
    const response = await fetch("/api/session", { signal });
    if (!response.ok) {
      throw new Error(`Failed to load session snapshot: ${response.status}`);
    }
    const nextSnapshot = (await response.json()) as BridgeSessionSnapshot;
    setSnapshot(nextSnapshot);
  }

  useEffect(() => {
    const controller = new AbortController();

    void refreshSnapshot(controller.signal).catch((loadError: Error) => {
      setError(loadError.message);
    });

    return () => controller.abort();
  }, []);

  useEffect(() => {
    let closed = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;

    const connect = () => {
      setConnectionState("connecting");
      socket = new WebSocket(buildWebSocketUrl(`/api/events/ws?after=${afterRef.current}`));

      socket.addEventListener("open", () => {
        if (!closed) {
          setConnectionState("open");
          setError(null);
        }
      });

      socket.addEventListener("message", (messageEvent) => {
        const batch = JSON.parse(messageEvent.data) as EventBatch;
        afterRef.current = batch.after;
        setEvents((previous) => [...previous, ...batch.events]);
        void refreshSnapshot().catch((loadError: Error) => {
          setError(loadError.message);
        });
      });

      socket.addEventListener("close", () => {
        if (closed) {
          setConnectionState("closed");
          return;
        }
        setConnectionState("connecting");
        reconnectTimer = window.setTimeout(connect, 1000);
      });

      socket.addEventListener("error", () => {
        setConnectionState("error");
        setError("The bridge event stream is unavailable.");
      });
    };

    connect();

    return () => {
      closed = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      socket?.close();
    };
  }, []);

  const latestEvents = useMemo(() => events.slice(-8).reverse(), [events]);
  const latestResource = useMemo(() => {
    if (snapshot.loaded_resources.length === 0) {
      return null;
    }
    return snapshot.loaded_resources[snapshot.loaded_resources.length - 1];
  }, [snapshot.loaded_resources]);

  return {
    snapshot,
    latestEvents,
    latestResource,
    connectionState,
    error,
  };
}