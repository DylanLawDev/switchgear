import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { ReactElement } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

export function renderWithProviders(ui: ReactElement, opts: { route?: string; path?: string } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter([{ path: opts.path ?? "*", element: ui }], {
    initialEntries: [opts.route ?? "/"],
  });
  return { qc, ...render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>) };
}
