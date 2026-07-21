import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

type ErrorSink = (message: string) => void;
let errorSink: ErrorSink = () => {};
export function setQueryErrorSink(sink: ErrorSink): void { errorSink = sink; }   // Toaster registers itself (Task 4)

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

export const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: (e) => errorSink(messageOf(e)) }),
  mutationCache: new MutationCache({
    onError: (e, _vars, _ctx, mutation) => {
      if (!mutation.meta?.inlineError) errorSink(messageOf(e));   // forms opt out (SPEC §6)
    },
  }),
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: true },
    mutations: { retry: 0 },
  },
});
