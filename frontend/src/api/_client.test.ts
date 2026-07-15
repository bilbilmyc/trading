/**
 * Tests for the shared fetch wrapper in src/api/_client.ts.
 *
 * The wrapper has three behaviours worth pinning:
 *   - 2xx → JSON.parse the body, return it
 *   - 4xx/5xx → throw `new Error(message)` where message is taken from
 *     `payload.detail` (FastAPI convention) or the response status text
 *   - 204/empty body → resolve to null without parsing
 *
 * The API_BASE resolver is also covered: it should read
 * `import.meta.env.VITE_API_BASE_URL` first, then fall back to
 * `http://127.0.0.1:8000` when the dev server port is 5173, and finally
 * to `window.location.origin` in production.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type FetchInput = Parameters<typeof fetch>[0];
type FetchInit = Parameters<typeof fetch>[1];

interface CapturedCall {
  input: FetchInput;
  init: FetchInit;
}

function mockFetch(impl: (input: FetchInput, init: FetchInit) => Promise<Response> | Response) {
  const calls: CapturedCall[] = [];
  const fn = vi.fn(async (input: FetchInput, init: FetchInit = {}) => {
    calls.push({ input, init });
    return await impl(input, init);
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

function jsonResponse(body: unknown, status = 200, statusText = "OK"): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText,
    headers: { "Content-Type": "application/json" },
  });
}

function emptyResponse(status = 204): Response {
  return new Response(null, { status, statusText: "No Content" });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.resetModules();
});

beforeEach(() => {
  // Force the resolver to take the dev-server fallback path (port 5173)
  // unless a test overrides VITE_API_BASE_URL via stubEnv.
  if (window.location.port !== "5173") {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, port: "5173" },
    });
  }
});

describe("request() — success paths", () => {
  it("parses the JSON body and returns it", async () => {
    mockFetch(() => jsonResponse({ ok: true, value: 42 }));
    const { request } = await import("./_client");
    const data = await request<{ ok: boolean; value: number }>("/health");
    expect(data).toEqual({ ok: true, value: 42 });
  });

  it("appends the path to API_BASE (which falls back to 127.0.0.1:8000 in dev)", async () => {
    const { calls } = mockFetch(() => jsonResponse({}));
    const { request } = await import("./_client");
    await request("/api/v1/engine/status");
    expect(calls).toHaveLength(1);
    const url = String(calls[0]!.input);
    expect(url).toMatch(/\/api\/v1\/engine\/status$/);
    expect(url.startsWith("http://127.0.0.1:8000")).toBe(true);
  });

  it("prepends VITE_API_BASE_URL when set", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test");
    const { calls } = mockFetch(() => jsonResponse({}));
    const { request } = await import("./_client");
    await request("/health");
    const url = String(calls[0]!.input);
    expect(url).toBe("https://api.example.test/health");
  });

  it("resolves to null when the body is empty (e.g. 204)", async () => {
    mockFetch(() => emptyResponse(204));
    const { request } = await import("./_client");
    const data = await request<null>("/api/v1/paper/reset", { method: "POST" });
    expect(data).toBeNull();
  });

  it("sends a JSON content-type header by default", async () => {
    const { calls } = mockFetch(() => jsonResponse({}));
    const { request } = await import("./_client");
    await request("/health");
    const headers = (calls[0]!.init!.headers ?? {}) as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("lets callers override headers (e.g. Authorization)", async () => {
    const { calls } = mockFetch(() => jsonResponse({}));
    const { request } = await import("./_client");
    await request("/api/v1/orders", {
      method: "POST",
      headers: { Authorization: "Bearer abc" },
      body: "{}",
    });
    const headers = (calls[0]!.init!.headers ?? {}) as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer abc");
    expect(headers["Content-Type"]).toBe("application/json");
  });
});

describe("request() — error paths", () => {
  it("throws an Error with the FastAPI detail message on 4xx", async () => {
    mockFetch(() => jsonResponse({ detail: "symbol not allowed" }, 400, "Bad Request"));
    const { request } = await import("./_client");
    await expect(request("/api/v1/orders", { method: "POST" })).rejects.toThrow(
      "symbol not allowed",
    );
  });

  it("falls back to the status text when the body has no detail", async () => {
    mockFetch(() => jsonResponse({ detail: null }, 503, "Service Unavailable"));
    const { request } = await import("./_client");
    await expect(request("/api/v1/orders")).rejects.toThrow("Service Unavailable");
  });

  it("falls back to the status text when the body is not JSON", async () => {
    mockFetch(
      () =>
        new Response("not json at all", {
          status: 500,
          statusText: "Internal Server Error",
        }),
    );
    const { request } = await import("./_client");
    await expect(request("/api/v1/orders")).rejects.toThrow("Internal Server Error");
  });

  it("stringifies an object detail body", async () => {
    mockFetch(() => jsonResponse({ detail: { msg: "no" } }, 400));
    const { request } = await import("./_client");
    await expect(request("/api/v1/orders")).rejects.toThrow(/no/);
  });
});
