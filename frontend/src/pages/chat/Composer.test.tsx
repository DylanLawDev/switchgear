import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Composer from "./Composer";

test("grows until half the chat height and then scrolls", async () => {
  const clientHeight = vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);
  const scrollHeight = vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(500);
  render(<div><Composer disabled={false} onSend={() => undefined} /></div>);

  await userEvent.setup().type(screen.getByRole("textbox"), "a long draft");

  expect(screen.getByRole("textbox")).toHaveStyle({ height: "300px", overflowY: "auto" });
  clientHeight.mockRestore();
  scrollHeight.mockRestore();
});
