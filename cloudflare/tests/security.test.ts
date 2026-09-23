import { describe, expect, it } from "vitest";
import { SECURITY_HEADERS, withSecurityHeaders } from "../src/security.js";

describe("security scaffolding", () => {
  it("adds the baseline browser security headers", () => {
    const response = withSecurityHeaders(new Response("ok"));
    for (const name of Object.keys(SECURITY_HEADERS)) {
      expect(response.headers.get(name)).toBe(SECURITY_HEADERS[name]);
    }
  });

  it("does not change response status or body", async () => {
    const response = withSecurityHeaders(new Response("ok", { status: 201 }));
    expect(response.status).toBe(201);
    expect(await response.text()).toBe("ok");
  });
});
