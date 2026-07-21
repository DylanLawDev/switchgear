import type { ChatEvent, ChatRequest } from "./types";
import { ApiError } from "./client";

export function parseSseChunk(buffer: string): { events: ChatEvent[]; rest: string } {
  const events: ChatEvent[] = [];
  let idx: number;
  while ((idx = buffer.indexOf("\n\n")) >= 0) {
    const line = buffer.slice(0, idx).trim();
    buffer = buffer.slice(idx + 2);
    if (line.startsWith("data: ")) events.push(JSON.parse(line.slice(6)) as ChatEvent);
  }
  return { events, rest: buffer };
}

export async function streamChat(body: ChatRequest, onEvent: (e: ChatEvent) => void,
                                 signal?: AbortSignal): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body), signal,
  });
  if (res.status === 401 || res.status === 403) { window.location.assign("/login"); return; }
  if (!res.ok || !res.body) throw new ApiError(res.status, `POST /api/chat -> ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parsed = parseSseChunk(buf);
    buf = parsed.rest;
    parsed.events.forEach(onEvent);
  }
}
