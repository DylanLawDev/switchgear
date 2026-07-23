import { useMutation, useQuery } from "@tanstack/react-query";
import { apiGet, apiSend } from "../client";
import { ClaimRequest, OkResponse, SetupStatus } from "../types";

export function useSetupStatus() {
  return useQuery({ queryKey: ["setup-status"], queryFn: () => apiGet<SetupStatus>("/api/setup/status") });
}

export function useClaim() {
  return useMutation({
    mutationFn: (body: ClaimRequest) => apiSend<OkResponse>("POST", "/api/setup/claim", body),
    meta: { inlineError: true },
  });
}
