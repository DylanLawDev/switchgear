import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../client";
import { CHANNEL_NAME } from "../../config";
import { ChannelStatus, FlaggedMessage, OkResponse, RecipientRule, SendFunction, SendFunctionParam, SuppressionRow } from "../types";

// SPEC §10 decision 3: v1 runs exactly one channel — every route below is scoped to it, and
// every query key is prefixed ["channels", CHANNEL_NAME, ...] so a future multi-channel UI
// can add the channel name as a real param without a cache-key migration.
const BASE = `/api/channels/${encodeURIComponent(CHANNEL_NAME)}`;

export function useChannelStatus() {
  return useQuery({
    queryKey: ["channels", CHANNEL_NAME, "status"],
    queryFn: () => apiGet<ChannelStatus>(BASE),
  });
}

export function usePollNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiSend<OkResponse>("POST", `${BASE}/poll`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels", CHANNEL_NAME, "status"] }),
  });
}

export function useFlagged() {
  return useQuery({
    queryKey: ["channels", CHANNEL_NAME, "flagged"],
    queryFn: () => apiGet<FlaggedMessage[]>(`${BASE}/flagged`),
  });
}

export function useRefile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      apiSend<OkResponse>("POST", `${BASE}/messages/${encodeURIComponent(key)}/refile`, { route: "file" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels", CHANNEL_NAME, "flagged"] }),
  });
}

export function useSendFunctions() {
  return useQuery({
    queryKey: ["channels", CHANNEL_NAME, "send-functions"],
    queryFn: () => apiGet<SendFunction[]>(`${BASE}/send-functions`),
  });
}

// Shape PUT to /send-functions/{name} — parity static/channels.js readForm(): server-owned
// fields (source, created_at, updated_at) are never sent.
export interface SendFunctionInput {
  name: string;
  description: string;
  params: Record<string, SendFunctionParam>;
  subject_template: string;
  body_template: string;
  recipient_rule: RecipientRule;
  gate: "approve" | "auto";
  rate_limit_per_day: number;
  enabled: boolean;
}

export function useSaveSendFunction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (doc: SendFunctionInput) =>
      apiSend<SendFunction>("PUT", `${BASE}/send-functions/${encodeURIComponent(doc.name)}`, doc),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels", CHANNEL_NAME, "send-functions"] }),
    meta: { inlineError: true }, // form renders the 400 detail inline, not a toast
  });
}

export function useDeleteSendFunction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiSend<OkResponse>("DELETE", `${BASE}/send-functions/${encodeURIComponent(name)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels", CHANNEL_NAME, "send-functions"] }),
  });
}

export function useSuppression() {
  return useQuery({
    queryKey: ["channels", CHANNEL_NAME, "suppression"],
    queryFn: () => apiGet<SuppressionRow[]>(`${BASE}/suppression`),
  });
}

export function useSuppress() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (address: string) => apiSend<OkResponse>("PUT", `${BASE}/suppression/${encodeURIComponent(address)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels", CHANNEL_NAME, "suppression"] }),
    meta: { inlineError: true }, // add-address form renders errors inline
  });
}

export function useUnsuppress() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (address: string) =>
      apiSend<OkResponse>("DELETE", `${BASE}/suppression/${encodeURIComponent(address)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels", CHANNEL_NAME, "suppression"] }),
  });
}
