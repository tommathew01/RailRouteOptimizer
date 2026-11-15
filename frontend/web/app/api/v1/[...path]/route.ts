import type { NextRequest } from "next/server";

import {
  UnsafePathError,
  buildBackendUrl,
  buildForwardHeaders,
  errorEnvelope,
  pickResponseHeaders,
} from "@/lib/proxy";

const BACKEND_URL = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
const TIMEOUT_MS = 30_000;
const MAX_BODY_BYTES = 64 * 1024;

function jsonError(status: number, code: string, message: string): Response {
  return new Response(errorEnvelope(code, message), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

async function forward(
  request: NextRequest,
  ctx: RouteContext<"/api/v1/[...path]">,
): Promise<Response> {
  const { path } = await ctx.params;
  let target: URL;
  try {
    target = buildBackendUrl(BACKEND_URL, path, request.nextUrl.search);
  } catch (error) {
    if (error instanceof UnsafePathError) return jsonError(400, "INVALID_PATH", "Invalid path.");
    throw error;
  }

  let body: ArrayBuffer | undefined;
  if (request.method === "POST") {
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) {
      return jsonError(413, "REQUEST_TOO_LARGE", "The request body is too large.");
    }
  }

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers: buildForwardHeaders(request.headers),
      body,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: pickResponseHeaders(upstream.headers),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      return jsonError(504, "BACKEND_TIMEOUT", "The RailRoute service did not respond in time.");
    }
    return jsonError(503, "BACKEND_UNAVAILABLE", "The RailRoute service is unavailable.");
  }
}

export { forward as GET, forward as POST };
