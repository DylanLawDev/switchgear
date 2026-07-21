// Transcribed from the FastAPI route modules + frozen contract (REQ §6.3).
// All timestamps are unix seconds (float) unless noted.

export type UiHome = "workflows" | "channels";

export interface WorkflowSummary {                    // GET /api/workflows (app.py _workflow_summaries)
  name: string; description: string; status: string; stale: boolean;
  ui_home?: UiHome;                                   // frozen contract; absent ⇒ "workflows"
}

export type FieldType =
  | "text" | "markdown" | "number" | "score" | "boolean" | "enum" | "status"
  | "timestamp" | "url" | "image" | "artifact" | "relation" | "json";   // model.py FIELD_TYPES

export interface FieldDef { type: FieldType; renderer?: string; max?: number; href_prefix?: string }

export interface KindDef {                            // model.py _parse_kind
  label: string; label_plural: string; collection: string; key_field: string;
  title_field: string; fields: Record<string, FieldDef>; list_fields: string[];
  detail_fields: string[] | null; sort: string[];
  expected_update_period: number | null; retention: number | null;
  item_ref_field?: string;                            // artifacts only
}

export interface ActionsDef {                         // model.py _parse_actions
  label: string; label_plural: string; collection: string; key_field: string;
  item_ref_field: string; executor: string; approval_ttl: number; draft_ttl: number;
}

export interface WorkflowDefinition {                 // GET /api/workflows/{name} (public_definition)
  name: string; description: string; body: string;
  text?: string;
  schema_version?: 1 | 2;
  items: KindDef | null; artifacts: KindDef | null; actions: ActionsDef | null;
  generate: { plugin: string; label: string } | null;
  intake?: { skills: string[] };                      // public_definition now includes this (PR #31); render-when-present tolerance stays (SPEC §5.4.2)
  execution?: WorkflowExecution | null;
}

export interface WorkflowStep {
  id: string; type: "agent" | "tool" | "transform"; when?: string;
  agent?: string; skills?: string[]; prompt?: string; context?: string;
  tool?: string; args?: Record<string, unknown> | string; expression?: string;
  output_schema?: Record<string, unknown>;
}
export interface WorkflowExecution {
  inputs: Record<string, unknown>; outputs: Record<string, unknown>;
  steps: WorkflowStep[]; output: string | null;
}

export type WorkflowRecord = Record<string, unknown>; // shaped rows: key_field (+item_ref_field) + declared fields

export interface ItemRef { key: string; title: string | null }

export type ActionStatus =                            // actions.py state machine (+legacy "submitted" ⇒ executed at read)
  | "draft" | "approved" | "executing" | "executed" | "failed"
  | "possibly_executed" | "rejected" | "expired" | "superseded" | "submitted";

export interface ActionRow {                          // GET .../actions (workflow_routes._action_row)
  key: string; item: ItemRef | null; status: ActionStatus; needs_you: number; created_at: number;
}

export interface ActionField {                        // actions.py sanitize_field
  selector: string; label: string; value: string; source: string;
  needs_you: boolean; kind: string;                   // "text" | "multiline" observed
}

export interface ActionRecord {
  status: ActionStatus; fields: ActionField[]; notes: string;
  created_at: number; updated_at: number; executed_at: number | null;
  rejected_comment?: string; screenshot?: string; confirmation_screenshot?: string;
  error?: string;                                     // 200-domain-refusal convention (SPEC §5.4.1)
  [k: string]: unknown;
}

export interface ItemDetailResponse { record: WorkflowRecord; artifacts: WorkflowRecord[]; actions: ActionRow[] }
export interface ArtifactDetailResponse { record: WorkflowRecord; item: ItemRef | null }
export interface ActionDetailResponse { record: ActionRecord; item: ItemRef | null }
export interface FieldUpdate { selector: string; value: string; needs_you: boolean }

// ---- chat (app.py) ----
export interface ConversationSummary { _id: string; title: string | null; updated_at: number | null }
export type ChatHistoryItem =
  | { kind: "message"; role: "user" | "assistant" | "error"; content: string }
  | { kind: "tool"; call_id: string; name: string; args: unknown; result?: unknown }
  | { kind: "status"; status: "running" };
export interface ChatRequest { conversation_id: string; message: string }
export interface ApprovalRef { kind: string; id: string; context?: string }
export interface ApprovalDetails extends ApprovalRef {
  status: string; title: string; before: string | null; after: string | null;
}
export type ChatEvent =                               // loop.py + app.py events()
  | { type: "text"; delta: string }
  | { type: "tool_call"; name: string; args: unknown }
  | { type: "tool_result"; name: string; result: string }
  | { type: "done"; usage: number }
  | { type: "error"; reason: string };

// ---- skills (app.py + skills/store.py) ----
export interface Skill { name: string; description: string; status: string; source: string; schedule: string | null }
export interface SkillDetail extends Skill { text: string; body: string; tools: string[] }
export interface SkillRun { skill?: string; ok?: boolean; at?: number; usage?: number; error?: string; [k: string]: unknown }

// ---- resources (storage_routes.py + resources/store.py + frozen contract) ----
export type ResourceKind = "csv" | "json" | "md" | "txt";
export interface ResourceSummary { name: string; kind: ResourceKind; description: string; size: number; source: string; updated_at: number }
export interface Resource extends ResourceSummary { content: string; created_at: number }
export interface ResourcePut { kind: ResourceKind; description: string; content: string }
export type WriteMode = "read-only" | "prompt" | "full";
export interface ResourceSettings { write_mode: WriteMode }   // GET/PUT /api/resources/settings
export interface PendingEdit {                                // GET /api/resources/pending
  id: string; resource_name: string; op: "create" | "update" | "delete";
  old_content: string | null; new_content: string | null;
  created_at: string;                                         // iso8601 (contract) — NOT unix seconds
  status: "pending";
}

// ---- memories (storage_routes.py + memory/store.py list/update shapes) ----
export type MemoryType = "core" | "episodic";
export type MemoryStatus = "active" | "archived" | "superseded";
export interface Memory {
  key: string; text: string; type: MemoryType; status: MemoryStatus;
  importance: number; source: string; conversation_id: string | null;
  superseded_by: string | null; embedding_model: string | null;
  created_at: number; updated_at: number; last_accessed_at: number | null; access_count: number;
}
export interface MemoryCreate { text: string; type: MemoryType; importance: number }

// ---- channels (channel_routes.py + channels/sendfns.py) ----
export interface ChannelStatus { name: string; address: string | null; transport: string | null; active: boolean; cursor: string | null; last_poll: number | null }
export interface RecipientRule { type: "fixed" | "reply_to_thread" | "allowlist" | "owner"; address?: string; addresses?: string[] }
export interface SendFunctionParam { type: "string" | "number" | "enum"; max_chars?: number; values?: string[] }
export interface SendFunction {
  name: string; description: string; params: Record<string, SendFunctionParam>;
  subject_template: string; body_template: string; recipient_rule: RecipientRule;
  gate: "approve" | "auto"; rate_limit_per_day: number; enabled: boolean;
  source: string; created_at: number; updated_at: number;
}
export interface SuppressionRow { address: string; added_at: number }
export interface FlaggedMessage { key: string; subject: string | null; sender: string | null; received_at: number | null; triage_reason: string | null }

export interface OkResponse { ok: true }

// ---- orchestration ----
export interface AgentProfileSummary {
  name: string; description: string; model_tier: "chat" | "bulk" | "writing";
  status: string; source: string; tools: string[] | null; resources: string[] | null;
  skills: string[] | null; updated_at: number;
}
export interface AgentProfile extends AgentProfileSummary { text: string; prompt: string; output_schema?: Record<string, unknown> }
export type ScheduleTrigger =
  | { kind: "cron"; cron: string; timezone: string }
  | { kind: "once"; run_at: string; timezone: string };
export type ScheduleInput =
  | { mode: "direct"; values: Record<string, unknown> }
  | { mode: "prompt"; prompt: string; resolver_agent?: string };
export interface WorkflowSchedule {
  id: string; name: string; workflow: string; enabled: boolean;
  trigger: ScheduleTrigger; input: ScheduleInput; allow_overlap: boolean;
  created_at: number; updated_at: number; last_run_at?: number | null;
}
export interface WorkflowRun {
  id: string; workflow: string; schedule_id?: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "needs_review";
  inputs: Record<string, unknown>; output: unknown; error?: string | null;
  created_at: number; updated_at: number;
}
export interface ApprovalSummary {
  kind: string; id: string; context?: string; status: string; origin: string;
  created_at: string | number;
  title: string;
}
export interface ReferenceSuggestion {
  path: string; label: string; type: string; description: string; has_children: boolean;
}

// ---- user settings (settings_routes.py) ----
export interface UserSettings {
  owner_email: string;
  model_chat: string;
  model_bulk: string;
  model_writing: string;
  run_token_budget: number;
  max_loop_iterations: number;
  resource_max_bytes: number;
  resource_read_chars: number;
  memory_max_chars: number;
  memory_core_max_chars: number;
  memory_recall_k: number;
  memory_recall_floor: number;
  memory_supersede_threshold: number;
  memory_recency_half_life_days: number;
  memory_reflection_min_interval: number;
  channel_body_max_chars: number;
  channel_backfill_max: number;
  channel_reply_rate_per_day: number;
}
