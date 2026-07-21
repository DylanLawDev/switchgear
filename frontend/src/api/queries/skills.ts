import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../client";
import { OkResponse, Skill, SkillDetail, SkillRun } from "../types";

export function useSkills() {
  return useQuery({ queryKey: ["skills"], queryFn: () => apiGet<Skill[]>("/api/skills") });
}

export function useSkill(name: string) {
  return useQuery({ queryKey: ["skills", name], queryFn: () => apiGet<SkillDetail>(`/api/skills/${encodeURIComponent(name)}`), enabled: !!name });
}

export function useSaveSkill(name: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (text: string) => apiSend<SkillDetail>("PUT", `/api/skills/${encodeURIComponent(name)}`, { text }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["skills"] }); qc.invalidateQueries({ queryKey: ["skills", name] }); } });
}

export function useSkillRuns(name: string) {
  return useQuery({
    queryKey: ["skills", name, "runs"],
    queryFn: () => apiGet<SkillRun[]>(`/api/skills/${encodeURIComponent(name)}/runs`),
    enabled: name.length > 0,
  });
}

export function useApproveSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiSend<OkResponse>("POST", `/api/skills/${encodeURIComponent(name)}/approve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills"] }),
  });
}

export function useRunSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiSend<OkResponse>("POST", `/api/skills/${encodeURIComponent(name)}/run`),
    onSuccess: (_data, name) => qc.invalidateQueries({ queryKey: ["skills", name, "runs"] }),
  });
}
