import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConfirmDialog from "./ConfirmDialog";

test("opens on trigger click and onConfirm fires only on the confirm button", async () => {
  const user = userEvent.setup();
  const onConfirm = vi.fn();
  render(
    <ConfirmDialog
      trigger={<button type="button">Open Delete Dialog</button>}
      title="Delete item?"
      body="This cannot be undone."
      confirmLabel="Confirm Delete"
      danger
      onConfirm={onConfirm}
    />,
  );

  expect(screen.queryByText("Delete item?")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Open Delete Dialog" }));
  expect(await screen.findByText("Delete item?")).toBeInTheDocument();
  expect(onConfirm).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "Confirm Delete" }));
  expect(onConfirm).toHaveBeenCalledTimes(1);
});

test("cancel closes the dialog without calling onConfirm", async () => {
  const user = userEvent.setup();
  const onConfirm = vi.fn();
  render(
    <ConfirmDialog
      trigger={<button type="button">Open</button>}
      title="Sure?"
      confirmLabel="Yes"
      onConfirm={onConfirm}
    />,
  );

  await user.click(screen.getByRole("button", { name: "Open" }));
  expect(await screen.findByText("Sure?")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /cancel/i }));
  expect(onConfirm).not.toHaveBeenCalled();
});
