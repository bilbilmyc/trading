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
  if (window.location.port === "5173") return "http://127.0.0.1:8000";
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
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(formatApiError(payload?.detail, response.statusText));
  }
  return payload as T;
}
