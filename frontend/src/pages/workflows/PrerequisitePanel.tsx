import { Link } from "react-router-dom";
import Badge from "../../components/Badge";
import { useResources } from "../../api/queries/resources";
import { useSkillRuns } from "../../api/queries/skills";
import styles from "./workflows.module.css";

type CheckState = "pass" | "fail" | "unverified";

function Chip({ state }: { state: CheckState }) {
  const glyph = state === "pass" ? "✓" : state === "fail" ? "✗" : "?";
  const tone = state === "pass" ? "ok" : state === "fail" ? "warn" : "dim";
  // The glyph is decorative — each row's adjacent text carries the real meaning, so the
  // glyph itself is aria-hidden (codebase convention: EmptyState's caret, WorkflowRail's
  // stale dot).
  return (
    <Badge tone={tone}>
      <span aria-hidden>{glyph}</span>
    </Badge>
  );
}

// SPEC §5.8 — job-hunt Runs empty state: two live prerequisite checks, rendered by
// ItemsSection only when workflowName === "job-hunt" and the items list is empty.
export default function PrerequisitePanel() {
  const { data: resources = [], isError: resourcesErrored } = useResources();
  const { data: runs = [], isError: runsErrored } = useSkillRuns("job-search");

  const hasCareerBank = resources.some((r) => r.name === "career-bank");
  // Distinguish "genuinely no career bank" from "couldn't check" (the query itself failed)
  // so the copy doesn't tell someone to add a career bank they may already have.
  const careerState: CheckState = hasCareerBank ? "pass" : resourcesErrored ? "unverified" : "fail";

  // No endpoint exposes env-var presence (frozen contract), so the JSearch check is
  // inferred from job-search run history (SPEC §5.8 decision). useSkillRuns is shared with
  // SkillsPage, where a fetch error SHOULD still raise the global toast (req §3.8) — this
  // panel must not swallow that error or it'd suppress the one legitimate report path.
  // Instead it degrades its own copy off the query's `isError` flag, landing on the same
  // "not yet verified" state an empty run list gets, rather than adding a second report.
  const latestRun = !runsErrored && runs.length > 0 ? runs[0] : null; // backend sorts runs desc by `at`
  const jsearchState: CheckState = !latestRun ? "unverified" : latestRun.ok ? "pass" : "fail";

  return (
    <div className={styles.prereqPanel}>
      <p className={styles.prereqIntro}>job-hunt needs two things before it can find anything:</p>
      <ul className={styles.prereqList}>
        <li className={styles.prereqRow}>
          <Chip state={careerState} />
          {careerState === "pass" && <span>career bank on file</span>}
          {careerState === "fail" && (
            <span>
              add your career bank — <Link to="/resources">resources</Link>
            </span>
          )}
          {careerState === "unverified" && <span>couldn't check — retry</span>}
        </li>
        <li className={styles.prereqRow}>
          <Chip state={jsearchState} />
          {jsearchState === "pass" && <span>job-search intake verified</span>}
          {jsearchState === "unverified" && (
            <span>not yet verified — run the job-search skill from /skills to check</span>
          )}
          {jsearchState === "fail" && (
            <span>
              intake ran and failed — check SWITCHGEAR_JSEARCH_API_KEY in the deploy env
              {latestRun?.error && <span className={styles.prereqError}> ({latestRun.error})</span>}
            </span>
          )}
        </li>
      </ul>
    </div>
  );
}
