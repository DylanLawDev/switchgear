import { http, HttpResponse } from "msw";
import { server } from "../test/msw";
import { apiGet, apiSend, ApiError } from "./client";

test("apiGet parses json", async () => {
  server.use(http.get("/api/skills", () => HttpResponse.json([{ name: "s" }])));
  await expect(apiGet("/api/skills")).resolves.toEqual([{ name: "s" }]);
});

test("non-ok surfaces FastAPI detail as ApiError", async () => {
  server.use(http.put("/api/resources/x", () =>
    HttpResponse.json({ detail: "kind is immutable" }, { status: 400 })));
  await expect(apiSend("PUT", "/api/resources/x", { kind: "md" }))
    .rejects.toMatchObject({ status: 400, detail: "kind is immutable" });
});

test("non-ok without json body falls back to method+path+status", async () => {
  server.use(http.get("/api/skills", () => new HttpResponse("boom", { status: 500 })));
  await expect(apiGet("/api/skills")).rejects.toBeInstanceOf(ApiError);
  await expect(apiGet("/api/skills")).rejects.toMatchObject({ detail: "GET /api/skills -> 500" });
});

test("401 redirects to /login", async () => {
  // jsdom's location is non-configurable — replace it wholesale.
  const original = window.location;
  const assign = vi.fn();
  // @ts-expect-error jsdom location replacement
  delete window.location;
  // @ts-expect-error jsdom location replacement
  window.location = { ...original, assign };
  server.use(http.get("/api/skills", () => HttpResponse.json({ detail: "not authenticated" }, { status: 401 })));
  void apiGet("/api/skills");             // promise intentionally never settles
  await vi.waitFor(() => expect(assign).toHaveBeenCalledWith("/login"));
  // @ts-expect-error restore
  window.location = original;
});
