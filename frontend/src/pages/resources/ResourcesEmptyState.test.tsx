import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ResourcesEmptyState from "./ResourcesEmptyState";

test("offers a generic create-resource action", async () => {
  const onCreate = vi.fn();
  const user = userEvent.setup();
  render(<ResourcesEmptyState onCreate={onCreate} />);

  await user.click(screen.getByRole("button", { name: "Create resource" }));
  expect(onCreate).toHaveBeenCalledOnce();
});
