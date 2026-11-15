import { describe, expect, it } from "vitest";

import {
  UnsafePathError,
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
