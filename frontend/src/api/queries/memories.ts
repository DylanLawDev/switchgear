import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../client";
import { Memory, MemoryCreate, OkResponse } from "../types";

export interface MemoryFilter { status?: string; type?: string }

// query string only carries set keys — parity with static/memories.js render()
function queryString(filter: MemoryFilter): string {
  const params = new URLSearchParams();
  if (filter.type) params.set("type", filter.type);
  if (filter.status) params.set("status", filter.status);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function useMemories(filter: MemoryFilter = {}) {
  return useQuery({
    queryKey: ["memories", filter],
    queryFn: () => apiGet<Memory[]>(`/api/memories${queryString(filter)}`),
  });
}

// shared invalidation: prefix match on ["memories"] clears every filter combination.
// meta.inlineError opts these out of the global queryClient.ts MutationCache error sink —
// MemoriesPage handles its own toasting (try/catch around mutateAsync) as the single error
// surface, same "forms opt out" convention documented in api/queryClient.ts.
function useMemoriesMutation<TVars, TResult>(mutationFn: (vars: TVars) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    meta: { inlineError: true },
    onSettled: () => qc.invalidateQueries({ queryKey: ["memories"] }),
  });
}

export function useCreateMemory() {
  return useMemoriesMutation((body: MemoryCreate) => apiSend<Memory>("POST", "/api/memories", body));
}

export function useUpdateMemory() {
  return useMemoriesMutation(({ key, text }: { key: string; text: string }) =>
    apiSend<Memory>("PUT", `/api/memories/${encodeURIComponent(key)}`, { text }));
}

export function useArchiveMemory() {
  return useMemoriesMutation((key: string) =>
    apiSend<Memory>("POST", `/api/memories/${encodeURIComponent(key)}/archive`));
}

export function useRestoreMemory() {
  return useMemoriesMutation((key: string) =>
    apiSend<Memory>("POST", `/api/memories/${encodeURIComponent(key)}/restore`));
}

export function useDeleteMemory() {
  return useMemoriesMutation((key: string) =>
    apiSend<OkResponse>("DELETE", `/api/memories/${encodeURIComponent(key)}`));
}
