import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../client";
import { ApprovalDetails, ApprovalRef, OkResponse } from "../types";

function path(ref: ApprovalRef): string {
  const base = `/api/approvals/${encodeURIComponent(ref.kind)}/${encodeURIComponent(ref.id)}`;
  return ref.context ? `${base}?context=${encodeURIComponent(ref.context)}` : base;
}

export function useApproval(ref: ApprovalRef) {
  return useQuery({
    queryKey: ["approvals", ref.kind, ref.id, ref.context ?? ""],
    queryFn: () => apiGet<ApprovalDetails>(path(ref)),
    enabled: ref.kind.length > 0 && ref.id.length > 0,
  });
}

export function useResolveApproval() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ref, action }: { ref: ApprovalRef; action: "approve" | "reject" }) =>
      apiSend<OkResponse>("POST", path(ref).split("?")[0], {
        action, context: ref.context ?? null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["resources"] });
      qc.invalidateQueries({ queryKey: ["skills"] });
      qc.invalidateQueries({ queryKey: ["workflows"] });
      qc.invalidateQueries({ queryKey: ["channels"] });
    },
  });
}
