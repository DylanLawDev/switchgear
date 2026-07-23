import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../client";
import { GatewayTestResult, OkResponse, UserSettings, UserSettingsUpdate } from "../types";

export function useUserSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => apiGet<UserSettings>("/api/settings") });
}

export function useSaveUserSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: UserSettingsUpdate) =>
      apiSend<UserSettings>("PUT", "/api/settings", settings),
    onSuccess: (settings) => qc.setQueryData(["settings"], settings),
    meta: { inlineError: true },
  });
}

export function useTestGateway() {
  return useMutation({
    mutationFn: (probe: { gateway_base_url?: string; gateway_api_key?: string }) =>
      apiSend<GatewayTestResult>("POST", "/api/settings/test-gateway", probe),
    meta: { inlineError: true },
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      apiSend<OkResponse>("POST", "/api/settings/password", body),
    meta: { inlineError: true },
  });
}

export function useLogout() {
  return useMutation({
    mutationFn: () => apiSend<OkResponse>("POST", "/auth/logout"),
    onSuccess: () => window.location.assign("/login"),
    meta: { inlineError: true },
  });
}
