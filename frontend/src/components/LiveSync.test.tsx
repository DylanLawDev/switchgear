import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import LiveSync from "./LiveSync";

class FakeEventSource {
  static instance: FakeEventSource;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();

  constructor(_url: string) {
    FakeEventSource.instance = this;
  }

  emit(topic: string) {
    this.onmessage?.({ data: JSON.stringify({ topic }) } as MessageEvent);
  }
}

test("invalidates the relevant query family when server data changes", async () => {
  vi.stubGlobal("EventSource", FakeEventSource);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { unmount } = render(
    <QueryClientProvider client={client}><LiveSync /></QueryClientProvider>,
  );

  act(() => FakeEventSource.instance.emit("conversations"));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["conversations"] }));

  unmount();
  expect(FakeEventSource.instance.close).toHaveBeenCalled();
  vi.unstubAllGlobals();
});
