import { http, HttpResponse } from "msw";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { server } from "../test/msw";
import SmartTextarea from "./SmartTextarea";

function Harness({ assist = false }: { assist?: boolean }) {
  const [value, setValue] = useState("");
  return <SmartTextarea value={value} onChange={setValue} aria-label="smart input"
    assistPreset={assist ? "prompt" : undefined} />;
}

test("@ opens keyboard-selectable typed reference suggestions", async () => {
  server.use(http.get("/api/references/suggest", () => HttpResponse.json([
    { path: "@resources", label: "resources", type: "namespace", has_children: true },
    { path: "@workflows", label: "workflows", type: "namespace", has_children: true },
  ])));
  const user = userEvent.setup();
  render(<Harness />);
  const input = screen.getByRole("textbox", { name: "smart input" });
  await user.type(input, "@");
  expect(await screen.findByRole("listbox", { name: "reference suggestions" })).toBeInTheDocument();
  await user.keyboard("{ArrowDown}{Enter}");
  expect(input).toHaveValue("@workflows.");
});

test("embedded help can replace the current draft", async () => {
  server.use(http.post("/api/assist/prompt", () => HttpResponse.json({
    ok: true, output: "Generated prompt",
  })));
  const user = userEvent.setup();
  render(<Harness assist />);
  await user.click(screen.getByRole("button", { name: "open embedded help" }));
  await user.type(screen.getByRole("textbox", { name: /What should/ }), "Make it clear");
  await user.click(screen.getByRole("button", { name: "Generate" }));
  await user.click(await screen.findByRole("button", { name: "Replace" }));
  expect(screen.getByRole("textbox", { name: "smart input" })).toHaveValue("Generated prompt");
});
