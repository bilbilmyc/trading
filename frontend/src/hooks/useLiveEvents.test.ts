/**
 * Tests for useLiveEvents — verifies the SSE subscription, payload
 * filtering, buffer truncation, reconnect reset, and cleanup.
 *
 * The hook reads the live EventSource so we install a fake class on
 * `globalThis` per test. Each fake records the URL it was constructed
 * with and exposes a `dispatch(payload)` helper that simulates an
 * `onmessage` callback. The `triggerOpen()` / `triggerError()` helpers
 * drive the reconnect / buffer-reset paths.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLiveEvents, type LiveEvent } from "./useLiveEvents";

interface FakeEventSource {
  url: string;
  listeners: {
    open: Array<() => void>;
    error: Array<() => void>;
  };
  onmessage: ((ev: { data: string }) => void) | null;
  closed: boolean;
  dispatch: (payload: unknown) => void;
  triggerOpen: () => void;
  triggerError: () => void;
  close: () => void;
}

const instances: FakeEventSource[] = [];

class FakeEventSourceCtor {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  url: string;
  onmessage: ((ev: { data: string }) => void) | null = null;
  closed = false;
  private listeners: { open: Array<() => void>; error: Array<() => void> } = {
    open: [],
    error: [],
  };

  constructor(url: string) {
    this.url = url;
    const self = this;
    // Build a wrapper that mirrors the Ctor's live state so tests can
    // observe `closed` / `onmessage` mutations through the same handle.
    const fake: FakeEventSource = {
      get url() {
        return self.url;
      },
      get listeners() {
        return self.listeners;
      },
      get onmessage() {
        return self.onmessage;
      },
      set onmessage(v) {
        self.onmessage = v;
      },
      get closed() {
        return self.closed;
      },
      dispatch: (payload: unknown) => {
        if (self.onmessage) self.onmessage({ data: JSON.stringify(payload) });
      },
      triggerOpen: () => self.listeners.open.forEach((fn) => fn()),
      triggerError: () => self.listeners.error.forEach((fn) => fn()),
      close: () => {
        self.closed = true;
      },
    };
    instances.push(fake);
  }

  addEventListener(name: "open" | "error", fn: () => void) {
    this.listeners[name].push(fn);
  }

  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  instances.length = 0;
  // @ts-expect-error — assigning test double to global EventSource
  globalThis.EventSource = FakeEventSourceCtor;
});

afterEach(() => {
  // @ts-expect-error — cleanup
  delete globalThis.EventSource;
});

function lastInstance(): FakeEventSource {
  const inst = instances[instances.length - 1];
  if (!inst) throw new Error("EventSource was not constructed");
  return inst;
}

function makeEvent(overrides: Partial<LiveEvent> = {}): LiveEvent {
  return {
    category: "system",
    event_type: "test_event",
    level: "info",
    message: "hello",
    timestamp: "2026-07-15T12:00:00.000000",
    ...overrides,
  };
}

describe("useLiveEvents — subscription", () => {
  it("opens the SSE stream with the expected URL", () => {
    renderHook(() => useLiveEvents());
    const inst = lastInstance();
    expect(inst.url).toBe("/api/v1/stream/events?heartbeat_seconds=10");
  });

  it("closes the EventSource on unmount", () => {
    const { unmount } = renderHook(() => useLiveEvents());
    const inst = lastInstance();
    expect(inst.closed).toBe(false);
    unmount();
    expect(inst.closed).toBe(true);
  });
});

describe("useLiveEvents — payload handling", () => {
  it("pushes kind:event payloads into the buffer (most recent first)", async () => {
    const { result } = renderHook(() => useLiveEvents());
    const inst = lastInstance();

    act(() => {
      inst.dispatch({ kind: "event", ...makeEvent({ message: "first" }) });
    });
    act(() => {
      inst.dispatch({ kind: "event", ...makeEvent({ message: "second" }) });
    });

    expect(result.current).toHaveLength(2);
    // Newest first — the second dispatch should be at index 0.
    expect(result.current[0]?.message).toBe("second");
    expect(result.current[1]?.message).toBe("first");
  });

  it("strips the kind discriminator from pushed events", () => {
    const { result } = renderHook(() => useLiveEvents());
    const inst = lastInstance();

    act(() => {
      inst.dispatch({ kind: "event", ...makeEvent() });
    });

    // The hook spreads `rest` (everything except `kind`) into the row.
    expect(result.current[0]).not.toHaveProperty("kind");
    expect(result.current[0]?.message).toBe("hello");
  });

  it("ignores heartbeats, snapshots, errors, and unknown kinds", () => {
    const { result } = renderHook(() => useLiveEvents());
    const inst = lastInstance();

    act(() => {
      inst.dispatch({ kind: "heartbeat", timestamp: "2026-07-15T12:00:00.000000" });
    });
    act(() => {
      inst.dispatch({ kind: "snapshot", strategies: [], risk: {} });
    });
    act(() => {
      inst.dispatch({ kind: "error", message: "boom" });
    });
    act(() => {
      inst.dispatch({ kind: "mystery", something: 1 });
    });

    expect(result.current).toHaveLength(0);
  });

  it("ignores non-JSON or empty payloads without throwing", () => {
    const { result } = renderHook(() => useLiveEvents());
    const inst = lastInstance();

    act(() => {
      // Bypass our dispatcher to feed raw garbage to onmessage.
      const handler = instances[0]?.onmessage;
      if (handler) handler({ data: "not json {" });
    });

    expect(result.current).toHaveLength(0);
  });
});

describe("useLiveEvents — buffer management", () => {
  it("truncates to MAX_BUFFERED (50) by dropping the oldest entries", () => {
    const { result } = renderHook(() => useLiveEvents());
    const inst = lastInstance();

    act(() => {
      for (let i = 0; i < 60; i += 1) {
        inst.dispatch({ kind: "event", ...makeEvent({ message: `m${i}` }) });
      }
    });

    expect(result.current).toHaveLength(50);
    // The first 10 (m0..m9) are gone; the most recent (m59) is at index 0.
    expect(result.current[0]?.message).toBe("m59");
    expect(result.current[49]?.message).toBe("m10");
  });

  it("resets the buffer on (re)connect so stale rows don't persist", () => {
    const { result } = renderHook(() => useLiveEvents());
    const inst = lastInstance();

    act(() => {
      inst.dispatch({ kind: "event", ...makeEvent({ message: "pre" }) });
    });
    expect(result.current).toHaveLength(1);

    act(() => {
      inst.triggerOpen();
    });
    expect(result.current).toHaveLength(0);
  });
});

describe("useLiveEvents — reconnect", () => {
  it("does not throw on error and lets the browser auto-reconnect", () => {
    const { result } = renderHook(() => useLiveEvents());
    const inst = lastInstance();

    // Pre-fill, then error, then reconnect + new event. New event should
    // be visible; the error itself must not have altered state.
    act(() => {
      inst.dispatch({ kind: "event", ...makeEvent({ message: "before" }) });
    });
    act(() => {
      inst.triggerError();
    });
    act(() => {
      inst.triggerOpen();
    });
    act(() => {
      inst.dispatch({ kind: "event", ...makeEvent({ message: "after-reconnect" }) });
    });

    expect(result.current.map((e) => e.message)).toEqual(["after-reconnect"]);
  });
});
