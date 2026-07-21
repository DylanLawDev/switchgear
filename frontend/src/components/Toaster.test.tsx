import { act, render, screen, within } from "@testing-library/react";
import Toaster, { toast } from "./Toaster";

afterEach(() => {
  vi.useRealTimers();
});

test("toast.error shows a visible status message and auto-dismisses after 5s", () => {
  vi.useFakeTimers();
  render(<Toaster />);

  act(() => {
    toast.error("boom");
  });
  const list = screen.getByRole("list");
  expect(within(list).getByRole("status")).toHaveTextContent("boom");

  act(() => {
    vi.advanceTimersByTime(5000);
  });
  expect(screen.queryByText("boom")).not.toBeInTheDocument();
});

test("toast.info shows a visible status message", () => {
  vi.useFakeTimers();
  render(<Toaster />);

  act(() => {
    toast.info("saved");
  });
  expect(screen.getByText("saved")).toBeInTheDocument();

  act(() => {
    vi.advanceTimersByTime(5000);
  });
});
