import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, v1Api } from "@/lib/api";

function mockFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

describe("v1Api request/requestEnvelope", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("resolves with the envelope's data on success", async () => {
    mockFetch({ success: true, message: "OK", data: { user_id: "u1", email: "a@b.com", created_at: "2026-01-01" } });
    await expect(v1Api.me()).resolves.toEqual({ user_id: "u1", email: "a@b.com", created_at: "2026-01-01" });
  });

  it("throws ApiError when the HTTP response itself fails", async () => {
    mockFetch({ success: false, message: "Invalid session token." }, 401);
    await expect(v1Api.me()).rejects.toMatchObject({ status: 401 });
  });

  it("throws ApiError when the envelope reports success: false despite a 200", async () => {
    mockFetch({ success: false, message: "Something went wrong" }, 200);
    await expect(v1Api.me()).rejects.toBeInstanceOf(ApiError);
  });

  it("sends credentials: include on every request - auth is a cookie, not a token this client attaches itself", async () => {
    const fetchMock = mockFetch({ success: true, message: "OK", data: null });
    await v1Api.me();
    expect(fetchMock).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ credentials: "include" }));
  });
});
