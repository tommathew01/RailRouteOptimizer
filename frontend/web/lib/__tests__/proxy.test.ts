import { describe, expect, it } from "vitest";

import {
  UnsafePathError,
  backendBaseUrl,
  buildBackendUrl,
  buildForwardHeaders,
  pickResponseHeaders,
} from "@/lib/proxy";

describe("buildBackendUrl", () => {
  it("maps segments and query string onto the backend /api/v1 path", () => {
    const url = buildBackendUrl("http://backend:8000", ["stations", "search"], "?q=tirur");
    expect(url.toString()).toBe("http://backend:8000/api/v1/stations/search?q=tirur");
  });

  it.each([[[".."]], [["trains", "..", "x"]], [["a b"]], [[]], [["%2e%2e"]]])(
    "rejects unsafe path %j",
    (segments) => {
      expect(() => buildBackendUrl("http://backend:8000", segments, "")).toThrow(UnsafePathError);
    },
  );
});

describe("header filtering", () => {
  it("forwards only allowlisted request headers plus the client address chain", () => {
    const incoming = new Headers({
      accept: "application/json",
      cookie: "session=secret",
      authorization: "Bearer nope",
      "x-forwarded-for": "203.0.113.7",
      "x-request-id": "req-12345678",
    });
    const forwarded = buildForwardHeaders(incoming);
    expect(forwarded.get("accept")).toBe("application/json");
    expect(forwarded.get("x-request-id")).toBe("req-12345678");
    expect(forwarded.get("x-forwarded-for")).toBe("203.0.113.7");
    expect(forwarded.has("cookie")).toBe(false);
    expect(forwarded.has("authorization")).toBe(false);
  });

  it("never caches proxied responses unless the backend says so", () => {
    const picked = pickResponseHeaders(new Headers({ "content-type": "application/json", "set-cookie": "x=1" }));
    expect(picked.get("cache-control")).toBe("no-store");
    expect(picked.has("set-cookie")).toBe(false);
  });
});

describe("backendBaseUrl", () => {
  it("keeps full URLs and adds http:// to a bare host:port (Render private service)", () => {
    expect(backendBaseUrl("http://backend:8000")).toBe("http://backend:8000");
    expect(backendBaseUrl("https://api.example.com")).toBe("https://api.example.com");
    expect(backendBaseUrl("railroute-backend-x1y2:8000")).toBe("http://railroute-backend-x1y2:8000");
    expect(backendBaseUrl(" ")).toBe("http://127.0.0.1:8000");
    expect(backendBaseUrl(undefined)).toBe("http://127.0.0.1:8000");
    expect(buildBackendUrl(backendBaseUrl("backend:8000"), ["meta"], "").toString()).toBe(
      "http://backend:8000/api/v1/meta",
    );
  });
});

describe("operator authorization", () => {
  const incoming = new Headers({ authorization: "Bearer ops-token", accept: "application/json" });

  it("is forwarded only to the token-protected operator endpoints", () => {
    expect(buildForwardHeaders(incoming, ["ops", "provider-quota"]).get("authorization")).toBe(
      "Bearer ops-token",
    );
    expect(buildForwardHeaders(incoming, ["metrics"]).get("authorization")).toBe("Bearer ops-token");
    expect(buildForwardHeaders(incoming, ["journeys", "optimize"]).has("authorization")).toBe(false);
    expect(buildForwardHeaders(incoming).has("authorization")).toBe(false);
  });
});
