import { useMutation, useQuery, useQueryClient, UseQueryResult } from "@tanstack/react-query";
import { ApiError, apiGet, apiSend } from "../client";
import {
  ActionDetailResponse,
  ActionRecord,
  ActionRow,
  ActionStatus,
  ArtifactDetailResponse,
  ItemDetailResponse,
  WorkflowDefinition,
  WorkflowRecord,
  WorkflowSummary,
} from "../types";

export function useWorkflows() {
  return useQuery({ queryKey: ["workflows"], queryFn: () => apiGet<WorkflowSummary[]>("/api/workflows") });
}

// SPEC §5.4: a missing ui_home defaults to "workflows" (the frozen contract's default).
export function railWorkflows(list: WorkflowSummary[]): WorkflowSummary[] {
  return list.filter((w) => (w.ui_home ?? "workflows") === "workflows");
}
export function channelWorkflows(list: WorkflowSummary[]): WorkflowSummary[] {
  return list.filter((w) => (w.ui_home ?? "workflows") === "channels");
}

export function useWorkflowDefinition(name: string) {
  return useQuery({
    queryKey: ["workflows", name],
    queryFn: () => apiGet<WorkflowDefinition>(`/api/workflows/${encodeURIComponent(name)}`),
    enabled: name.length > 0,
  });
}

export function useSaveWorkflowDefinition(name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => apiSend<WorkflowDefinition>("PUT", `/api/workflows/${encodeURIComponent(name)}/definition`, { text }),
    onSuccess: (data) => {
      qc.setQueryData(["workflows", name], data);
      qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

export function useWorkflowKind(name: string, kind: "actions"): UseQueryResult<ActionRow[]>;
export function useWorkflowKind(name: string, kind: "items" | "artifacts"): UseQueryResult<WorkflowRecord[]>;
export function useWorkflowKind(name: string, kind: "items" | "artifacts" | "actions") {
  return useQuery({
    queryKey: ["workflows", name, kind],
    queryFn: () => apiGet<(WorkflowRecord | ActionRow)[]>(`/api/workflows/${encodeURIComponent(name)}/${kind}`),
    enabled: name.length > 0,
  });
}

export function useWorkflowRecord(name: string, kind: "items", key: string): UseQueryResult<ItemDetailResponse>;
export function useWorkflowRecord(
  name: string,
  kind: "artifacts",
  key: string,
): UseQueryResult<ArtifactDetailResponse>;
export function useWorkflowRecord(name: string, kind: "actions", key: string): UseQueryResult<ActionDetailResponse>;
export function useWorkflowRecord(name: string, kind: "items" | "artifacts" | "actions", key: string) {
  return useQuery({
    queryKey: ["workflows", name, kind, key],
    queryFn: () =>
      apiGet<ItemDetailResponse | ArtifactDetailResponse | ActionDetailResponse>(
        `/api/workflows/${encodeURIComponent(name)}/${kind}/${encodeURIComponent(key)}`,
      ),
    enabled: name.length > 0 && key.length > 0,
  });
}

interface GenerateResult {
  error?: string;
  [k: string]: unknown;
}

export function useGenerate(name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      apiSend<GenerateResult>("POST", `/api/workflows/${encodeURIComponent(name)}/items/${encodeURIComponent(key)}/generate`),
    onSuccess: (data, key) => {
      if (data.error) return; // 200-domain-refusal (SPEC §5.4.1) — no cache write
      qc.invalidateQueries({ queryKey: ["workflows", name, "artifacts"] });
      qc.invalidateQueries({ queryKey: ["workflows", name, "items", key] });
    },
    meta: { inlineError: true }, // caller renders {error} / thrown errors inline (SPEC §6)
  });
}

// SPEC §10 decision 2 — exactly the statuses with an enabled owner verb in the state machine.
export const PENDING_STATUSES = ["draft", "approved", "failed", "possibly_executed"] as const;

async function fetchActionsOrEmpty(name: string): Promise<ActionRow[]> {
  try {
    return await apiGet<ActionRow[]>(`/api/workflows/${encodeURIComponent(name)}/actions`);
  } catch (e) {
    // A workflow with no `actions` block 404s on the kind route (workflow_routes.py
    // _kind_or_404) — that's not an error worth toasting, just "no actions".
    if (e instanceof ApiError && e.status === 404) return [];
    throw e;
  }
}

function pendingCountOptions(name: string) {
  return {
    queryKey: ["workflows", name, "actions"] as const,
    queryFn: () => fetchActionsOrEmpty(name),
    select: (rows: ActionRow[]) =>
      rows.filter((r) => (PENDING_STATUSES as readonly string[]).includes(r.status)).length,
  };
}

export function usePendingCount(name: string) {
  return useQuery(pendingCountOptions(name));
}

// ---- gated-action flow (SPEC §5.4.1) ----

// Draft returns the full action record (start_draft's dict) or a {error} 200-domain-refusal
// (e.g. "no actions configured") — parity workflow_routes.py `act`.
export function useDraftAction(name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      apiSend<ActionRecord>("POST", `/api/workflows/${encodeURIComponent(name)}/items/${encodeURIComponent(key)}/act`),
    onSuccess: (data, key) => {
      if (data.error) return; // 200-domain-refusal (SPEC §5.4.1) — no cache write
      qc.invalidateQueries({ queryKey: ["workflows", name, "actions"] });
      qc.invalidateQueries({ queryKey: ["workflows", name, "items", key] });
    },
    meta: { inlineError: true }, // caller renders {error} / thrown errors inline (SPEC §6)
  });
}

export type ActionVerbName = "fields" | "approve" | "reject" | "execute" | "confirm";

export interface ActionVerbParams {
  key: string;
  verb: ActionVerbName;
  body?: unknown;
}

// One mutation for all five verbs — parity workflow.js saveFields/approveAction/rejectAction/
// executeAction/confirmAction, unified: POST /api/workflows/{name}/actions/{key}/{verb}. On
// 2xx: {error} is a domain refusal (e.g. "resolve NEEDS-YOU fields before approving") — the
// caller renders it inline (SPEC §5.4.1 refreshAction) and no per-action cache write happens,
// but the actions list is still refetched (parity refreshAction's unconditional
// `renderActions()` — badges/table reflect any partial mutation regardless of the refusal).
// On genuine success, patch the per-action cache entry too.
export function useActionVerb(name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, verb, body }: ActionVerbParams) =>
      apiSend<ActionRecord>(
        "POST",
        `/api/workflows/${encodeURIComponent(name)}/actions/${encodeURIComponent(key)}/${verb}`,
        body,
      ),
    onSuccess: (data, { key }) => {
      qc.invalidateQueries({ queryKey: ["workflows", name, "actions"] });
      if (data.error) return; // 200-domain-refusal — NO per-action cache write, caller shows it inline
      qc.setQueryData<ActionDetailResponse>(["workflows", name, "actions", key], (prev) =>
        prev ? { ...prev, record: data } : prev,
      );
    },
    meta: { inlineError: true },
  });
}

// Exact port of static/workflow.js ACTION_BUTTONS — buttons always render, disabled when the
// record's status isn't in `when`. The server re-checks every transition; this is convenience
// gating only, never enforcement.
export const ACTION_BUTTONS = [
  { id: "save", label: "Save fields", when: ["draft", "failed"] },
  { id: "approve", label: "Approve", when: ["draft", "failed"] },
  { id: "reject", label: "Reject", when: ["draft", "failed", "approved"] },
  { id: "execute", label: "Execute", when: ["approved"], confirm: true },
  { id: "confirm-executed", label: "Mark executed", when: ["possibly_executed"], confirm: true },
  { id: "confirm-failed", label: "Mark failed", when: ["possibly_executed"] },
] as const satisfies readonly { id: string; label: string; when: readonly ActionStatus[]; confirm?: true }[];
