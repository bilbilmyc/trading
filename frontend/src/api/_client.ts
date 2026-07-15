/**
 * Shared HTTP client for the trading backend.
 *
 * All other `src/api/*.ts` modules import `request` from here. This keeps
 * the fetch wrapper, base-URL resolution, and error formatting in one
 * place so changes (e.g. adding an auth header, switching to axios)
 * happen once.
 */

function resolveApiBase(): string {
  if (import.meta.env.VITE_API_BASE_URL) return import.meta.env.VITE_API_BASE_URL;
  if (window.location.port === "5180") return "http://127.0.0.1:8000";
  return window.location.origin;
}

export const API_BASE = resolveApiBase();

function formatApiError(message: unknown, fallback: string): string {
  if (!message) return fallback;
  if (typeof message === "string") return message;
  if (Array.isArray(message)) return JSON.stringify(message);
  if (typeof message === "object") {
    const maybeMessage = (message as { message?: unknown }).message;
    if (typeof maybeMessage === "string") return maybeMessage;
    return JSON.stringify(message);
  }
  return String(message);
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    // Caller-provided headers are merged on top of the default JSON
    // Content-Type, so the caller's `Authorization` survives a body
    // payload and the default survives when they don't override it.
    // Putting `headers` AFTER `...init` is intentional — a spread
    // `init` would otherwise clobber the header map entirely.
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> | undefined),
    },
  });

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      // Non-JSON body (e.g. an HTML 502 from a reverse proxy). Leave
      // payload as null so the error path falls through to statusText.
      payload = null;
    }
  }
  if (!response.ok) {
    throw new Error(formatApiError((payload as { detail?: unknown } | null)?.detail, response.statusText));
  }
  return payload as T;
}
