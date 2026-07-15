/**
 * useLiveEvents — subscribes to /api/v1/stream/events over SSE and
 * returns a rolling buffer of the most recent events.
 *
 * Replaces the previous 5s polling through EngineContext.events (which
 * only ever surfaced 12 events at a time and was always 0–5s stale).
 * The backend SSE emits `kind: "event"` payloads as they arrive in
 * SQLite plus `kind: "heartbeat"` every 10s for liveness; we keep
 * only events for the drawer.
 *
 * Auto-reconnects on transient failures. The browser's native
 * EventSource handles retries; we just re-arm the local state on
 * `onopen` so a reconnect resets the buffer to fresh data.
 */

import { useEffect, useState } from "react";

export interface LiveEvent {
  category?: string;
  event_type?: string;
  level?: string;
  message?: string;
  timestamp?: string;
  exchange?: string;
  symbol?: string;
}

const MAX_BUFFERED = 50;

export function useLiveEvents(): LiveEvent[] {
  const [events, setEvents] = useState<LiveEvent[]>([]);

  useEffect(() => {
    const es = new EventSource("/api/v1/stream/events?heartbeat_seconds=10");

    es.addEventListener("open", () => {
      // Reset buffer on (re)connect so we don't show stale rows from a
      // prior process. Heartbeats and snapshots arrive within a few
      // hundred ms; the buffer fills back up as alerts fire.
      setEvents([]);
    });

    es.onmessage = (ev: MessageEvent<string>) => {
      let data: unknown;
      try {
        data = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!data || typeof data !== "object") return;
      const payload = data as { kind?: string } & LiveEvent;
      if (payload.kind === "event") {
        // Strip the discriminator before pushing it into the buffer.
        const { kind: _kind, ...rest } = payload;
        void _kind;
        setEvents((prev) => {
          const next = [rest as LiveEvent, ...prev];
          if (next.length > MAX_BUFFERED) next.length = MAX_BUFFERED;
          return next;
        });
      }
      // Heartbeats / snapshots / errors: ignore for the drawer but the
      // SSE connection itself stays open.
    };

    es.onerror = () => {
      // EventSource auto-reconnects. Mark nothing — the next open()
      // handler will reset the buffer.
    };

    return () => {
      es.close();
    };
  }, []);

  return events;
}
