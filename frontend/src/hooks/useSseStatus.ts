/**
 * useSseStatus — connection-level liveness for the SSE stream.
 *
 * Distinct from useLiveEvents (which surfaces parsed event payloads).
 * This hook is for "is the pipe open?" diagnostics — used by the
 * SettingsPage and the Spine to render a tiny connection indicator.
 *
 * The EventSource state machine is:
 *   0 CONNECTING  (re)establishing
 *   1 OPEN        live
 *   2 CLOSED      browser gave up
 *
 * We additionally track `lastEventAt` (ms epoch of the most recent
 * inbound payload) so a UI can show "heartbeat 2s ago" / "silent for
 * 30s" without keeping a separate timer.
 */

import { useEffect, useState } from "react";

export type SseConnectionState = "connecting" | "open" | "closed";

export interface SseStatus {
  state: SseConnectionState;
  /** ms-since-epoch of the most recent inbound message, or null. */
  lastEventAt: number | null;
}

export function useSseStatus(url: string): SseStatus {
  const [state, setState] = useState<SseConnectionState>("connecting");
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);

  useEffect(() => {
    const es = new EventSource(url);
    setState("connecting");

    const onOpen = () => setState("open");
    const onMessage = () => setLastEventAt(Date.now());
    const onError = () => {
      // EventSource auto-retries. While the retry is pending the state
      // is CONNECTING; only mark closed if the browser has given up.
      if (es.readyState === EventSource.CLOSED) {
        setState("closed");
      } else {
        setState("connecting");
      }
    };

    es.addEventListener("open", onOpen);
    es.onmessage = onMessage;
    es.onerror = onError;

    return () => {
      es.close();
    };
  }, [url]);

  return { state, lastEventAt };
}
