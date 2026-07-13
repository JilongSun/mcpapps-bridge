import { useEffect, useMemo, useRef, useState } from "react";

import type {
  BridgeSessionDetail,
  BridgeSessionRecord,
  BridgeSessionSnapshot,
  EventBatch,
  SessionEvent,
} from "../types";

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
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<BridgeSessionSnapshot>(EMPTY_SNAPSHOT);
  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [error, setError] = useState<string | null>(null);
  const afterRef = useRef(0);

  async function refreshSnapshot(currentSessionId: string, signal?: AbortSignal) {
    const response = await fetch(`/api/sessions/${currentSessionId}`, { signal });
    if (!response.ok) {
      throw new Error(`Failed to load session snapshot: ${response.status}`);
    }
    const detail = (await response.json()) as BridgeSessionDetail;
    setSnapshot(detail.snapshot);
  }

  useEffect(() => {
    const controller = new AbortController();

    void fetch("/api/sessions", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Failed to list bridge sessions: ${response.status}`);
        }
        const sessions = (await response.json()) as BridgeSessionRecord[];
        const currentSession = sessions.find((session) => session.status !== "closed") ?? sessions[0];
        if (currentSession === undefined) {
          throw new Error("The bridge has no managed sessions.");
        }
        setSessionId(currentSession.session_id);
        await refreshSnapshot(currentSession.session_id, controller.signal);
      })
      .catch((loadError: Error) => {
        if (loadError.name !== "AbortError") {
          setError(loadError.message);
        }
      });

    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (sessionId === null) {
      return;
    }
    let closed = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;

    const connect = () => {
      setConnectionState("connecting");
      socket = new WebSocket(
        buildWebSocketUrl(`/api/sessions/${sessionId}/events/ws?after=${afterRef.current}`),
      );

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
        void refreshSnapshot(sessionId).catch((loadError: Error) => {
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
  }, [sessionId]);

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