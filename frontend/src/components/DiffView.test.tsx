import { render, screen } from "@testing-library/react";
import DiffView from "./DiffView";

test("renders one removed line and one added line for a changed resource", () => {
  render(<DiffView oldContent={"a\nb\n"} newContent={"a\nc\n"} />);

  const removed = screen.getByText("b").closest("[data-line-type]") as HTMLElement;
  const added = screen.getByText("c").closest("[data-line-type]") as HTMLElement;
  const unchanged = screen.getByText("a").closest("[data-line-type]") as HTMLElement;

  expect(removed).toHaveAttribute("data-line-type", "remove");
  expect(added).toHaveAttribute("data-line-type", "add");
  expect(unchanged).toHaveAttribute("data-line-type", "same");
});

test("null oldContent (create) renders every line as added", () => {
  render(<DiffView oldContent={null} newContent={"one\ntwo\n"} />);

  expect(screen.getByText("one").closest("[data-line-type]")).toHaveAttribute("data-line-type", "add");
  expect(screen.getByText("two").closest("[data-line-type]")).toHaveAttribute("data-line-type", "add");
});

test("null newContent (delete) renders every line as removed", () => {
  render(<DiffView oldContent={"one\ntwo\n"} newContent={null} />);

  expect(screen.getByText("one").closest("[data-line-type]")).toHaveAttribute("data-line-type", "remove");
  expect(screen.getByText("two").closest("[data-line-type]")).toHaveAttribute("data-line-type", "remove");
});
