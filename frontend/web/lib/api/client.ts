/**
 * Typed client for the RailRoute API (same-origin `/api/v1`). Every response is validated with
 * Zod so the UI never renders provider data whose shape it does not understand.
 */
import type { z } from "zod";

import { ErrorEnvelopeSchema } from "./schemas";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId: string | null = null,
    readonly details: Record<string, unknown> | null = null,
    readonly retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type RequestOptions<S extends z.ZodType> = {
  method?: "GET" | "POST";
  body?: unknown;
  schema: S;
  signal?: AbortSignal;
};

export async function apiRequest<S extends z.ZodType>(
  path: string,
  { method = "GET", body, schema, signal }: RequestOptions<S>,
): Promise<z.infer<S>> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers: {
        accept: "application/json",
        ...(body === undefined ? {} : { "content-type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("Network error. Check your connection and try again.", 0, "NETWORK_ERROR");
  }

  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const parsed = ErrorEnvelopeSchema.safeParse(payload);
    const retryAfter = Number(response.headers.get("retry-after"));
    if (parsed.success) {
      const { code, message, request_id, details } = parsed.data.error;
      throw new ApiError(
        message,
        response.status,
        code,
        request_id ?? null,
        details ?? null,
        Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
      );
    }
    throw new ApiError(`Request failed (${response.status}).`, response.status, "HTTP_ERROR");
  }

  const result = schema.safeParse(payload);
  if (!result.success) {
    throw new ApiError(
      "The service returned data in an unexpected format.",
      response.status,
      "INVALID_RESPONSE",
    );
  }
  return result.data;
}
