import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../client";
import { OkResponse, UserSettings } from "../types";

export function useUserSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => apiGet<UserSettings>("/api/settings") });
}

export function useSaveUserSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: Omit<UserSettings, "owner_email">) =>
      apiSend<UserSettings>("PUT", "/api/settings", settings),
    onSuccess: (settings) => qc.setQueryData(["settings"], settings),
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
