import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../client";
import {
  OkResponse,
  PendingEdit,
  Resource,
  ResourcePut,
  ResourceSettings,
  ResourceSummary,
  WriteMode,
} from "../types";
import { toast } from "../../components/Toaster";

export function useResources() {
  return useQuery({ queryKey: ["resources"], queryFn: () => apiGet<ResourceSummary[]>("/api/resources") });
}

export function useResource(name: string) {
  return useQuery({
    queryKey: ["resources", name],
    queryFn: () => apiGet<Resource>(`/api/resources/${encodeURIComponent(name)}`),
    enabled: name.length > 0,
  });
}

function invalidateResource(qc: ReturnType<typeof useQueryClient>, name: string) {
  qc.invalidateQueries({ queryKey: ["resources"] });
  qc.invalidateQueries({ queryKey: ["resources", name] });
  qc.invalidateQueries({ queryKey: ["resources", "pending"] });
}

export function useSaveResource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, body }: { name: string; body: ResourcePut }) =>
      apiSend<Resource>("PUT", `/api/resources/${encodeURIComponent(name)}`, body),
    meta: { inlineError: true },                       // form renders the 400 detail inline, not a toast
    onSuccess: (_data, { name }) => invalidateResource(qc, name),
  });
}

export function useDeleteResource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiSend<OkResponse>("DELETE", `/api/resources/${encodeURIComponent(name)}`),
    onSuccess: (_data, name) => invalidateResource(qc, name),
  });
}

export function useWriteMode() {
  return useQuery({
    queryKey: ["resources", "settings"],
    queryFn: () => apiGet<ResourceSettings>("/api/resources/settings"),
  });
}

export function useSetWriteMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (write_mode: WriteMode) =>
      apiSend<ResourceSettings>("PUT", "/api/resources/settings", { write_mode }),
    meta: { inlineError: true },                        // we toast ourselves below; avoid a double toast
    onMutate: async (write_mode) => {
      await qc.cancelQueries({ queryKey: ["resources", "settings"] });
      const previous = qc.getQueryData<ResourceSettings>(["resources", "settings"]);
      qc.setQueryData<ResourceSettings>(["resources", "settings"], { write_mode });
      return { previous };
    },
    onError: (err, _write_mode, ctx) => {
      if (ctx?.previous) qc.setQueryData(["resources", "settings"], ctx.previous);
      toast.error(err instanceof Error ? err.message : String(err));
    },
  });
}

export function usePendingEdits() {
  return useQuery({
    queryKey: ["resources", "pending"],
    queryFn: () => apiGet<PendingEdit[]>("/api/resources/pending"),
    refetchInterval: 30_000,
  });
}

export function useResolvePendingEdit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" }) =>
      apiSend<OkResponse>("POST", `/api/resources/pending/${encodeURIComponent(id)}/${action}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["resources"] });
      qc.invalidateQueries({ queryKey: ["resources", "pending"] });
    },
  });
}

export const RESOURCE_NAME_RE = /^[a-z0-9][a-z0-9-]{1,63}$/;

export interface ResourceGroup {
  key: "career" | "user" | "agent" | "other";
  label: string;
  items: ResourceSummary[];
}

// SPEC §10 decision 10: career bank by name prefix, then user/agent/other by source.
export function groupResources(list: ResourceSummary[]): ResourceGroup[] {
  const career: ResourceSummary[] = [];
  const user: ResourceSummary[] = [];
  const agent: ResourceSummary[] = [];
  const other: ResourceSummary[] = [];
  for (const r of list) {
    if (r.name === "career-bank" || r.name.startsWith("career-")) career.push(r);
    else if (r.source === "user") user.push(r);
    else if (r.source === "agent") agent.push(r);
    else other.push(r);
  }
  return [
    { key: "career", label: "career bank", items: career },
    { key: "user", label: "user", items: user },
    { key: "agent", label: "agent", items: agent },
    { key: "other", label: "other", items: other },
  ];
}
