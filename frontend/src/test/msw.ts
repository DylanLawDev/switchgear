// msw.ts — empty default handler set; each test/page-suite `server.use(...)`es its own.
import { setupServer } from "msw/node";
export const server = setupServer();
