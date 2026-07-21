import { parseSseChunk } from "./sse";

test("parses complete frames and keeps the remainder", () => {
  const { events, rest } = parseSseChunk('data: {"type":"text","delta":"hi"}\n\ndata: {"type":"do');
  expect(events).toEqual([{ type: "text", delta: "hi" }]);
  expect(rest).toBe('data: {"type":"do');
});

test("multiple frames in one chunk", () => {
  const { events } = parseSseChunk(
    'data: {"type":"tool_call","name":"x","args":{}}\n\ndata: {"type":"done","usage":5}\n\n',
  );
  expect(events.map((e) => e.type)).toEqual(["tool_call", "done"]);
});

test("ignores non-data lines", () => {
  expect(parseSseChunk(": ping\n\n").events).toEqual([]);
});
