import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { useConversationMessages, useConversations } from "../api/queries/conversations";
import { streamChat } from "../api/sse";
import { ChatEvent } from "../api/types";
import EmptyState from "../components/EmptyState";
import ConversationRail from "./chat/ConversationRail";
import MessageList, { TranscriptItem } from "./chat/MessageList";
import Composer from "./chat/Composer";
import styles from "./ChatPage.module.css";

let nextItemId = 0;

export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlId = searchParams.get("c");
  const [newConversationId, setNewConversationId] = useState(() => crypto.randomUUID());
  const [wantsNew, setWantsNew] = useState(false);
  const conversationId = urlId ?? newConversationId;

  const qc = useQueryClient();
  const { data: conversations = [] } = useConversations();

  // A bare visit resumes the most recent conversation; an explicit "New chat"
  // (wantsNew) or an empty instance keeps the fresh-conversation behavior.
  useEffect(() => {
    if (!urlId && !wantsNew && conversations.length > 0) {
      setSearchParams({ c: conversations[0]._id }, { replace: true });
    }
  }, [urlId, wantsNew, conversations, setSearchParams]);
  const { data: history } = useConversationMessages(conversationId);

  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [streaming, setStreaming] = useState(false);
  const assistantIdRef = useRef<number | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  // Tracks which conversation is "current" for guarding a send's callbacks — a send
  // captures the conversation id it was fired for and compares against this ref so
  // stragglers from an aborted/switched-away stream are dropped silently.
  const currentConversationIdRef = useRef(conversationId);

  useEffect(() => {
    currentConversationIdRef.current = conversationId;
    // A conversation switch invalidates any in-flight stream for the previous
    // conversation — abort it so its remaining events can't leak into the new
    // conversation's transcript, and reset streaming state for the new conversation.
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    assistantIdRef.current = null;
    setStreaming(false);
  }, [conversationId]);

  useEffect(() => {
    const running = (history ?? []).some((item) => item.kind === "status");
    // While this mounted page owns the SSE viewer, its event callbacks are the
    // lowest-latency renderer. Live-query refreshes are for reconnect/navigation.
    if (abortControllerRef.current === null) {
      setTranscript(
        (history ?? [])
          .filter((item) => item.kind !== "status")
          .map((item) => ({ ...item, id: ++nextItemId } as TranscriptItem)),
      );
      setStreaming(running);
    }
  }, [history]);

  useEffect(() => () => abortControllerRef.current?.abort(), []);

  function onEvent(forConversationId: string, e: ChatEvent) {
    if (forConversationId !== currentConversationIdRef.current) return;
    if (e.type === "text") {
      setTranscript((prev) => {
        if (assistantIdRef.current !== null) {
          return prev.map((item) =>
            item.kind === "message" && item.id === assistantIdRef.current
              ? { ...item, content: item.content + e.delta }
              : item,
          );
        }
        const id = ++nextItemId;
        assistantIdRef.current = id;
        return [...prev, { kind: "message", id, role: "assistant", content: e.delta }];
      });
    } else if (e.type === "tool_call") {
      setTranscript((prev) => [...prev, { kind: "tool", id: ++nextItemId, name: e.name, args: e.args }]);
    } else if (e.type === "tool_result") {
      let parsedResult: unknown = e.result;
      try { parsedResult = JSON.parse(e.result); } catch { /* plain-text tool output */ }
      setTranscript((prev) => {
        const idx = [...prev].reverse().findIndex((item) => item.kind === "tool" && item.result === undefined);
        if (idx === -1) return prev;
        const realIdx = prev.length - 1 - idx;
        const target = prev[realIdx];
        if (target.kind !== "tool") return prev;
        const copy = [...prev];
        copy[realIdx] = { ...target, result: parsedResult };
        return copy;
      });
      qc.invalidateQueries({ queryKey: ["resources", "pending"] });
    } else if (e.type === "error") {
      setTranscript((prev) => [...prev, { kind: "message", id: ++nextItemId, role: "error", content: e.reason }]);
    } else if (e.type === "done") {
      qc.invalidateQueries({ queryKey: ["conversations"] });
    }
  }

  function startNewChat() {
    abortControllerRef.current?.abort();
    assistantIdRef.current = null;
    setWantsNew(true);
    setNewConversationId(crypto.randomUUID());
    setSearchParams({}, { replace: false });
    setTranscript([]);
  }

  async function handleSend(text: string) {
    if (!urlId) setSearchParams({ c: conversationId }, { replace: true });
    const sentConversationId = conversationId;
    assistantIdRef.current = null;
    setTranscript((prev) => [...prev, { kind: "message", id: ++nextItemId, role: "user", content: text }]);
    setStreaming(true);
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    try {
      await streamChat(
        { conversation_id: sentConversationId, message: text },
        (e) => onEvent(sentConversationId, e),
        controller.signal,
      );
    } catch (err) {
      // A conversation switch aborts the previous stream — that's a clean cancellation,
      // not a failure, and must not render an error bubble.
      const isAbort = err instanceof DOMException && err.name === "AbortError";
      if (!isAbort && sentConversationId === currentConversationIdRef.current) {
        const reason = err instanceof Error ? err.message : String(err);
        setTranscript((prev) => [...prev, { kind: "message", id: ++nextItemId, role: "error", content: reason }]);
      }
    } finally {
      if (sentConversationId === currentConversationIdRef.current) {
        abortControllerRef.current = null;
        setStreaming(false);
        void qc.invalidateQueries({ queryKey: ["conversations", sentConversationId] });
      }
    }
  }

  const showEmptyState = conversations.length === 0 && transcript.length === 0 && !streaming;

  return (
    <div className={styles.page}>
      <ConversationRail conversations={conversations} currentId={urlId} onNewChat={startNewChat} />
      <div className={styles.main}>
        {showEmptyState ? (
          <EmptyState heading="no conversations yet" />
        ) : (
          <MessageList items={transcript} streaming={streaming} />
        )}
        <Composer disabled={streaming} onSend={handleSend} autoFocus />
      </div>
    </div>
  );
}
