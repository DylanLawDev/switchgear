import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../client";
import {
  AgentProfile, AgentProfileSummary, ApprovalSummary, OkResponse,
  WorkflowRun, WorkflowSchedule,
} from "../types";

export function useAgents() {
  return useQuery({ queryKey: ["agents"], queryFn: () => apiGet<AgentProfileSummary[]>("/api/agents") });
}
export function useAgent(name: string) {
  return useQuery({ queryKey: ["agents", name], queryFn: () => apiGet<AgentProfile>(`/api/agents/${encodeURIComponent(name)}`), enabled: !!name });
}
export function useSaveAgent() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: ({ name, text }: { name: string; text: string }) =>
    apiSend<AgentProfile>("PUT", `/api/agents/${encodeURIComponent(name)}`, { text }),
  onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }) });
}
export function useDeleteAgent() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (name: string) => apiSend<OkResponse>("DELETE", `/api/agents/${encodeURIComponent(name)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }) });
}
export function useTestAgent() {
  return useMutation({ mutationFn: ({ name, prompt }: { name: string; prompt: string }) =>
    apiSend<{ ok: boolean; output?: unknown; error?: string }>("POST", `/api/agents/${encodeURIComponent(name)}/test`, { prompt }) });
}

export function useSchedules() {
  return useQuery({ queryKey: ["schedules"], queryFn: () => apiGet<WorkflowSchedule[]>("/api/schedules") });
}
export function useScheduleRuns(id: string) {
  return useQuery({ queryKey: ["schedules", id, "runs"],
    queryFn: () => apiGet<WorkflowRun[]>(`/api/schedules/${encodeURIComponent(id)}/runs`),
    enabled: !!id });
}
export function useSaveSchedule() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: ({ id, body }: { id?: string; body: Omit<WorkflowSchedule, "id" | "created_at" | "updated_at"> }) =>
    apiSend<WorkflowSchedule>(id ? "PUT" : "POST", id ? `/api/schedules/${encodeURIComponent(id)}` : "/api/schedules", body),
  onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }) });
}
export function useDeleteSchedule() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => apiSend<OkResponse>("DELETE", `/api/schedules/${encodeURIComponent(id)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }) });
}
export function useRunSchedule() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => apiSend<{ ok: boolean; run?: WorkflowRun }>("POST", `/api/schedules/${encodeURIComponent(id)}/run`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }) });
}
export function useScheduleState() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
    apiSend<WorkflowSchedule>("POST", `/api/schedules/${encodeURIComponent(id)}/${enabled ? "enable" : "disable"}`),
  onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }) });
}

export function useApprovalInbox() {
  return useQuery({ queryKey: ["approvals"], queryFn: () => apiGet<ApprovalSummary[]>("/api/approvals") });
}
