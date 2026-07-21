import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

function rootsFor(topic: string): string[][] {
  if (topic === "conversations") return [["conversations"]];
  if (topic === "resources" || topic.startsWith("resource-")) return [["resources"]];
  if (topic === "memories") return [["memories"]];
  if (topic === "skills") return [["skills"], ["workflows"]];
  if (topic === "runs" || topic === "schedules") return [["skills"], ["workflows"]];
  if (topic === "workflow-runs") return [["workflow-runs"], ["workflows"], ["schedules"]];
  if (topic === "workflow-schedules") return [["schedules"]];
  if (topic === "agent-profiles" || topic === "agent-runs") return [["agents"]];
  if (topic === "definition-pending" || topic === "skill-pending" || topic === "resource-pending") return [["approvals"]];
  if (topic === "app-settings") return [["settings"]];
  if (topic.startsWith("wf-")) return [["workflows"], ["channels"]];
  if (topic.startsWith("channel") || topic === "send-functions") return [["channels"]];
  return [];
}

export default function LiveSync() {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const pending = new Set<string>();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const source = new EventSource("/api/events");
    source.onmessage = (event) => {
      const topic = (JSON.parse(event.data) as { topic?: string }).topic;
      if (!topic || topic === "connected") return;
      pending.add(topic);
      if (timer) return;
      timer = setTimeout(() => {
        const roots = new Map<string, string[]>();
        pending.forEach((item) => rootsFor(item).forEach((root) => roots.set(root.join("/"), root)));
        pending.clear();
        timer = undefined;
        if (roots.size === 0) {
          void queryClient.invalidateQueries();
        } else {
          roots.forEach((queryKey) => void queryClient.invalidateQueries({ queryKey }));
        }
      }, 75);
    };
    source.onerror = () => {
      // EventSource reconnects automatically. Window-focus refetch remains a fallback.
    };
    return () => {
      source.close();
      if (timer) clearTimeout(timer);
    };
  }, [queryClient]);

  return null;
}
