import { channelWorkflows, railWorkflows } from "./workflows";
import { WorkflowSummary } from "../types";

// Same shape as the WorkflowsPage.test.tsx rail fixture — direct unit coverage of the
// ui_home filter/default contract (SPEC §5.4) these two exported filters implement.
// job-hunt declares ui_home:"workflows"; channel-email declares ui_home:"channels";
// research has no ui_home key at all (must default to "workflows").
const fixture: WorkflowSummary[] = [
  { name: "job-hunt", description: "", status: "active", stale: true, ui_home: "workflows" },
  { name: "channel-email", description: "", status: "active", stale: false, ui_home: "channels" },
  { name: "research", description: "", status: "active", stale: false },
];

test("railWorkflows keeps ui_home:workflows plus ui_home-absent entries, excludes ui_home:channels", () => {
  expect(railWorkflows(fixture).map((w) => w.name)).toEqual(["job-hunt", "research"]);
});

test("channelWorkflows keeps only ui_home:channels entries", () => {
  expect(channelWorkflows(fixture).map((w) => w.name)).toEqual(["channel-email"]);
});
