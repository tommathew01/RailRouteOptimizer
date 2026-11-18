/**
 * Pure helpers for the same-origin API proxy (app/api/v1/[...path]/route.ts).
 *
 * The browser only ever talks to this Next.js origin. The proxy forwards an allowlisted set of
 * headers to the FastAPI backend, whose URL is read at runtime (one image, many environments).
 * No provider credentials exist anywhere in the frontend.
 */

const SAFE_SEGMENT = /^[A-Za-z0-9._-]{1,64}$/;

export const FORWARDED_REQUEST_HEADERS = ["accept", "content-type", "x-request-id"] as const;
export const FORWARDED_RESPONSE_HEADERS = [
  "content-type",
  "x-request-id",
  "retry-after",
  "cache-control",
  "location",
] as const;

export class UnsafePathError extends Error {}

/**
 * The backend base URL from `BACKEND_INTERNAL_URL`. Platforms that link services by address
 * (e.g. Render's private-service `hostport`) supply `host:port` without a scheme; internal
 * traffic is plain HTTP on the private network, so `http://` is assumed then.
 */
export function backendBaseUrl(configured: string | undefined): string {
  const value = (configured ?? "").trim();
  if (!value) return "http://127.0.0.1:8000";
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(value) ? value : `http://${value}`;
}

/** Build the backend URL for `/api/v1/<segments>?<search>`; rejects traversal and odd input. */
export function buildBackendUrl(base: string, segments: readonly string[], search: string): URL {
  if (segments.length === 0 || segments.length > 8) {
    throw new UnsafePathError("unsupported path depth");
  }
  for (const segment of segments) {
    if (!SAFE_SEGMENT.test(segment) || segment === "." || segment === "..") {
      throw new UnsafePathError("unsupported path segment");
    }
  }
  const url = new URL(`/api/v1/${segments.join("/")}`, base);
  url.search = search.startsWith("?") || search === "" ? search : `?${search}`;
  return url;
}

/**
 * Operator endpoints (`/api/v1/metrics`, `/api/v1/ops/*`) are the only ones that read
 * `Authorization`: the backend checks a Bearer token (METRICS_TOKEN) and answers 404 without one
 * outside development. Forwarding it for these paths lets operators monitor quota usage and
 * calibrate TRUSTED_PROXY_HOPS through the public URL while the backend stays private.
 */
export function isOperatorPath(segments: readonly string[]): boolean {
  return segments[0] === "metrics" || segments[0] === "ops";
}

/** Copy only allowlisted headers; append the client address chain for backend rate limiting. */
export function buildForwardHeaders(incoming: Headers, segments: readonly string[] = []): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = incoming.get(name);
    if (value) headers.set(name, value);
  }
  const authorization = incoming.get("authorization");
  if (authorization && isOperatorPath(segments)) headers.set("authorization", authorization);
  const forwardedFor = incoming.get("x-forwarded-for");
  if (forwardedFor) headers.set("x-forwarded-for", forwardedFor);
  return headers;
}

export function pickResponseHeaders(upstream: Headers): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.get(name);
    if (value) headers.set(name, value);
  }
  if (!headers.has("cache-control")) headers.set("cache-control", "no-store");
  return headers;
}

export function errorEnvelope(code: string, message: string): string {
  return JSON.stringify({ error: { code, message, request_id: null } });
}
