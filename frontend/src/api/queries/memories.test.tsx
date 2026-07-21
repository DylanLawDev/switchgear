import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { ReactNode } from "react";
import { server } from "../../test/msw";
import { useRestoreMemory } from "./memories";

// Regression for review finding: memories mutations set meta.inlineError so the app's global
// MutationCache error sink (api/queryClient.ts "forms opt out" convention) does not also fire
// — MemoriesPage is the single error surface (try/catch + toast.error) for these mutations.
test("memories mutations opt out of a MutationCache global error sink via meta.inlineError", async () => {
  server.use(
    http.post("/api/memories/m1/restore", () =>
      HttpResponse.json({ detail: "memory not found" }, { status: 404 }),
    ),
  );

  const sink = vi.fn();
  const qc = new QueryClient({
    mutationCache: new MutationCache({
      onError: (_err, _vars, _ctx, mutation) => {
        if (!mutation.meta?.inlineError) sink();   // mirrors api/queryClient.ts
      },
    }),
    defaultOptions: { mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );

  const { result } = renderHook(() => useRestoreMemory(), { wrapper });

  await expect(result.current.mutateAsync("m1")).rejects.toThrow("memory not found");

  expect(sink).not.toHaveBeenCalled();
});
