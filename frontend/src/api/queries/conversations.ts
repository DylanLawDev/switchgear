import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import { ChatHistoryItem, ConversationSummary } from "../types";

export function useConversations() {
  return useQuery({
    queryKey: ["conversations"],
    queryFn: () => apiGet<ConversationSummary[]>("/api/conversations"),
  });
}

export function useConversationMessages(id: string) {
  return useQuery({
    queryKey: ["conversations", id],
    queryFn: () => apiGet<ChatHistoryItem[]>(`/api/conversations/${encodeURIComponent(id)}`),
    staleTime: Infinity,   // history is append-only from our side (SPEC §5.2)
  });
}
