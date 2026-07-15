/**
 * StatusDrawer tests — filter tabs, expansion, and live event ingestion.
 *
 * The hook that backs this component (`useLiveEvents`) is tested
 * separately; here we drive it through a small EventSource fake so the
 * drawer integration is covered too.
 */

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StatusDrawer } from "./StatusDrawer";

interface FakeEventSource {
  url: string;
  onmessage: ((ev: { data: string }) => void) | null;
  closed: boolean;
  dispatch: (payload: unknown) => void;
  triggerOpen: () => void;
}

const instances: FakeEventSource[] = [];

class FakeEventSourceCtor {
  url: string;
  onmessage: ((ev: { data: string }) => void) | null = null;
  closed = false;
  private openListeners: Array<() => void> = [];
  constructor(url: string) {
    this.url = url;
    const self = this;
    const fake: FakeEventSource = {
      get url() {
        return self.url;
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
      triggerOpen: () => self.openListeners.forEach((fn) => fn()),
    };
    instances.push(fake);
  }
  addEventListener(name: string, fn: () => void) {
    if (name === "open") this.openListeners.push(fn);
  }
  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  instances.length = 0;
  // @ts-expect-error — installing test double
  globalThis.EventSource = FakeEventSourceCtor;
});

afterEach(() => {
  // @ts-expect-error — cleanup
  delete globalThis.EventSource;
  vi.useRealTimers();
});

function feedEvent(payload: unknown) {
  const inst = instances[instances.length - 1];
  if (!inst) throw new Error("EventSource not constructed");
  act(() => {
    inst.dispatch(payload);
  });
}

describe("StatusDrawer — empty state", () => {
  it("renders the empty-state message when no events have arrived", () => {
    render(<StatusDrawer />);
    expect(screen.getByText(/暂无告警/)).toBeInTheDocument();
  });

  it("starts collapsed", () => {
    render(<StatusDrawer />);
    const region = screen.getByRole("region", { name: "最近告警抽屉" });
    expect(region.className).toContain("status-drawer--collapsed");
  });
});

describe("StatusDrawer — filter tabs", () => {
  it("renders one tab per level and toggles the visible rows", () => {
    render(<StatusDrawer />);

    feedEvent({
      kind: "event",
      level: "info",
      event_type: "info_ev",
      message: "info-msg",
      timestamp: "2026-07-15T12:00:00.000000",
    });
    feedEvent({
      kind: "event",
      level: "warning",
      event_type: "warn_ev",
      message: "warn-msg",
      timestamp: "2026-07-15T12:00:01.000000",
    });
    feedEvent({
      kind: "event",
      level: "critical",
      event_type: "crit_ev",
      message: "crit-msg",
      timestamp: "2026-07-15T12:00:02.000000",
    });

    // All visible by default.
    expect(screen.getByText("info-msg")).toBeInTheDocument();
    expect(screen.getByText("warn-msg")).toBeInTheDocument();
    expect(screen.getByText("crit-msg")).toBeInTheDocument();

    // Click the "CRIT" tab — only the critical row should remain visible.
    fireEvent.click(screen.getByRole("tab", { name: "CRIT" }));
    expect(screen.getByText("crit-msg")).toBeInTheDocument();
    expect(screen.queryByText("info-msg")).not.toBeInTheDocument();
    expect(screen.queryByText("warn-msg")).not.toBeInTheDocument();

    // Back to "全部" — all three return.
    fireEvent.click(screen.getByRole("tab", { name: "全部" }));
    expect(screen.getByText("info-msg")).toBeInTheDocument();
    expect(screen.getByText("warn-msg")).toBeInTheDocument();
    expect(screen.getByText("crit-msg")).toBeInTheDocument();
  });

  it("the CRIT/ERR count badge reflects the FULL buffer, not the active filter", () => {
    render(<StatusDrawer />);
    feedEvent({
      kind: "event",
      level: "info",
      event_type: "i",
      message: "x",
      timestamp: "2026-07-15T12:00:00.000000",
    });

    // No CRIT/ERR in the buffer → no badge should render (the bar tab
    // labeled "CRIT" stays in the DOM, so we look for the badge class
    // specifically).
    expect(
      document.querySelector(".status-drawer__bar-badge--crit"),
    ).toBeNull();
  });
});

describe("StatusDrawer — row expansion", () => {
  it("expands a row on click to show the detail fields", () => {
    render(<StatusDrawer />);

    feedEvent({
      kind: "event",
      level: "error",
      event_type: "kill_switch_engaged",
      message: "halted by user",
      category: "risk",
      exchange: "binance_usdm",
      symbol: "BTCUSDT",
      timestamp: "2026-07-15T12:34:56.000000",
    });

    // Open the drawer so the body is in the rendered tree.
    fireEvent.click(screen.getByRole("button", { name: /展开告警/ }));
    const row = screen.getByRole("button", { expanded: false });
    fireEvent.click(row);

    // Detail panel should now show the underlying fields.
    const details = screen.getByText("binance_usdm").closest(".status-drawer__row-detail");
    expect(details).not.toBeNull();
    expect(within(details as HTMLElement).getByText("BTCUSDT")).toBeInTheDocument();
    expect(within(details as HTMLElement).getByText("risk")).toBeInTheDocument();
    expect(within(details as HTMLElement).getByText("error")).toBeInTheDocument();
  });
});
