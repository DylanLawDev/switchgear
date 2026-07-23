import { render, screen } from "@testing-library/react";
import MessageList from "./MessageList";

test("plan tool results render as a checklist", () => {
  render(
    <MessageList
      streaming={false}
      items={[{
        kind: "tool", id: 1, name: "plan", args: { op: "set" },
        result: {
          title: "Job pipeline setup",
          tasks: [
            { text: "create career bank", status: "done" },
            { text: "propose workflow", status: "in_progress" },
            { text: "schedule intake", status: "pending" },
            { text: "old idea", status: "skipped" },
          ],
        },
      }]}
    />,
  );
  expect(screen.getByText("Job pipeline setup")).toBeInTheDocument();
  expect(screen.getByText("create career bank")).toBeInTheDocument();
  const items = screen.getAllByRole("listitem");
  expect(items).toHaveLength(4);
  expect(items[0]).toHaveAttribute("data-status", "done");
  expect(items[1]).toHaveAttribute("data-status", "in_progress");
});

test("malformed plan result falls back to generic tool details", () => {
  render(
    <MessageList
      streaming={false}
      items={[{ kind: "tool", id: 1, name: "plan", args: {}, result: { error: "bad" } }]}
    />,
  );
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});
