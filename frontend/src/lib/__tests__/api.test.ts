import { api, ApiError, onUnauthorized } from "@/lib/api";

describe("api client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.cookie = "tgads_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("sends the CSRF cookie back as a header on writes", async () => {
    document.cookie = "tgads_csrf=abc123";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response('{"ok":true}', { status: 200 }));
    await api.post("/x", { a: 1 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/x");
    expect((init!.headers as Record<string, string>)["X-CSRF-Token"]).toBe("abc123");
    expect(init!.body).toBe('{"a":1}');
  });

  it("does not send CSRF on reads", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await api.get("/y");
    expect((fetchMock.mock.calls[0][1]!.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("turns problem JSON into ApiError and notifies on 401", async () => {
    const seen = vi.fn();
    const off = onUnauthorized(seen);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response('{"status":401,"code":"unauthorized","detail":"ابتدا وارد شوید."}', { status: 401 }),
    );
    await expect(api.get("/z")).rejects.toMatchObject({ status: 401, code: "unauthorized", message: "ابتدا وارد شوید." });
    expect(seen).toHaveBeenCalledOnce();
    off();
  });

  it("does not log out on a wrong password", async () => {
    const seen = vi.fn();
    const off = onUnauthorized(seen);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response('{"code":"wrong_password","detail":"رمز اشتباه است."}', { status: 401 }),
    );
    await expect(api.post("/auth/login", {})).rejects.toBeInstanceOf(ApiError);
    expect(seen).not.toHaveBeenCalled();
    off();
  });

  it("reports network failures in Persian", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.get("/n")).rejects.toMatchObject({ code: "network" });
  });
});
