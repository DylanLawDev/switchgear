import "@testing-library/jest-dom/vitest";

// jsdom lacks matchMedia; theme bootstrap and reduced-motion checks need it.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false, media: query, onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  }),
});

// jsdom lacks ResizeObserver; @radix-ui/react-radio-group (RadioRow) sizes its indicator with it.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

import { server } from "./msw";
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
  patchRequestForJsdomAbortSignals();
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// jsdom implements its own AbortController/AbortSignal (see jsdom's
// AbortController-impl.js) rather than delegating to Node's native undici
// classes. Node's real `Request` constructor brand-checks `init.signal`
// against its own internal AbortSignal and rejects jsdom's — normally never
// hit in this codebase (no app code constructs AbortControllers), but
// react-router's data router (RouterProvider) constructs one internally for
// every navigation, and MSW's request interceptor routes ALL `new Request()`
// calls (including that internal one) through the real, strict constructor.
// Retry once with the signal stripped rather than trying to resurrect a
// pristine native AbortController (there is no supported way to reach one
// once jsdom's environment setup has shadowed the global) — real router
// navigation tests (useBlocker guards) need this to construct a Request at
// all; the (never exercised in tests) navigation-cancellation behavior is
// the only thing given up.
function patchRequestForJsdomAbortSignals(): void {
  const OriginalRequest = globalThis.Request;
  Object.defineProperty(globalThis, "Request", {
    configurable: true,
    writable: true,
    value: new Proxy(OriginalRequest, {
      construct(target, args, newTarget) {
        try {
          return Reflect.construct(target, args, newTarget);
        } catch (err) {
          const init = args[1] as RequestInit | undefined;
          if (init && "signal" in init && err instanceof TypeError) {
            return Reflect.construct(target, [args[0], { ...init, signal: undefined }], newTarget);
          }
          throw err;
        }
      },
    }),
  });
}
