export type ReviewStatus =
  | "queued"
  | "indexing"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type Severity = "critical" | "major" | "minor" | "nitpick";

export type FindingCategory =
  | "correctness"
  | "security"
  | "performance"
  | "style"
  | "tests"
  | "architecture";

export type FindingStatus = "proposed" | "verified" | "rejected" | "published";

export type FeedbackVerdict = "useful" | "false_positive" | "wontfix";

export type ChangeType = "added" | "modified" | "deleted" | "renamed";

export type DiffSide = "old" | "new";

export type EgressPolicy = "local_only" | "allow_cloud" | "allow_training_cloud";

/** Насколько далеко уезжает код ради ответа модели. */
export type ModelTrust = "local" | "private_remote" | "training_remote";

export interface AvailableModel {
  name: string;
  model: string;
  trust: ModelTrust;
  supports_tools: boolean;
  context_window: number;
  note: string;
}

export interface Repository {
  id: string;
  tenant_id: string;
  name: string;
  vcs_provider: string;
  remote_url: string | null;
  default_branch: string;
  local_path: string;
  egress_policy: EgressPolicy;
  created_at: string;
}

export interface Hunk {
  old_start: number;
  old_lines: number;
  new_start: number;
  new_lines: number;
  header: string;
}

export interface ReviewFile {
  id: string;
  path: string;
  previous_path: string | null;
  change_type: ChangeType;
  language: string | null;
  added_lines: number;
  removed_lines: number;
  is_too_large: boolean;
  hunks: Hunk[];
}

export interface Finding {
  id: string;
  file_path: string;
  line_start: number;
  line_end: number;
  side: DiffSide;
  severity: Severity;
  category: FindingCategory;
  status: FindingStatus;
  title: string;
  body_markdown: string;
  suggested_patch: string | null;
  confidence: number | null;
  producer_name: string;
  latest_verdict: FeedbackVerdict | null;
}

export type ReviewStage = "build_context" | "plan_review" | "review" | "aggregate" | "verify";

export type DegradationKind =
  | "context_overflow"
  | "output_exhausted"
  | "invalid_output"
  | "timeout"
  | "rate_limited"
  | "provider_unavailable"
  | "context_unavailable"
  | "unknown";

/** Кто, где и почему не отработал. Вид причины приходит полем, а не текстом. */
export interface NodeDegradation {
  stage: ReviewStage;
  file_path: string;
  kind: DegradationKind;
  detail: string;
  reviewer: string | null;
  model: string | null;
}

export interface ReviewRun {
  id: string;
  repository_id: string;
  source: string;
  status: ReviewStatus;
  base_sha: string;
  head_sha: string;
  head_subject: string | null;
  totals: Record<string, number>;
  failure_reason: string | null;
  degradations: NodeDegradation[];
  duration_ms: number;
  files_with_context: number;
  reviewable_files: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  files: ReviewFile[];
  findings: Finding[];
}

export interface ReviewRunSummary {
  id: string;
  repository_id: string;
  status: ReviewStatus;
  base_sha: string;
  head_sha: string;
  head_subject: string | null;
  totals: Record<string, number>;
  severity_counts: Record<string, number>;
  findings_total: number;
  rejected_count: number;
  created_at: string;
  changed_files: number;
}

export interface FilePatch {
  path: string;
  previous_path: string | null;
  change_type: ChangeType;
  language: string | null;
  added_lines: number;
  removed_lines: number;
  is_too_large: boolean;
  patch_size_bytes: number;
  patch: string;
  context_side: DiffSide;
  total_lines: number | null;
}

export interface FileContext {
  path: string;
  side: DiffSide;
  commit_sha: string;
  start_line: number;
  end_line: number;
  total_lines: number;
  lines: string[];
}

export interface Feedback {
  id: string;
  verdict: FeedbackVerdict;
  comment: string | null;
  created_at: string;
}

export interface MarkedFinding {
  run_id: string;
  finding_id: string;
  file_path: string;
  line_start: number;
  severity: Severity;
  category: FindingCategory;
  title: string;
  producer_name: string;
  verdict: FeedbackVerdict;
  comment: string | null;
  marked_at: string;
}

export interface FeedbackDigest {
  marked: MarkedFinding[];
  counts: Record<string, number>;
  marked_count: number;
  total_findings: number;
  useful_share: number | null;
}

export type SnapshotStatus = "pending" | "running" | "ready" | "failed" | "cancelled";

export type SnapshotStage = "parsing" | "storing" | "linking" | "embedding" | "complete";

export interface IndexStats {
  files_total: number;
  files_parsed: number;
  files_reused: number;
  files_stored: number;
  symbols: number;
  chunks: number;
  edges: number;
  edges_resolved: number;
}

export interface VectorCoverage {
  chunks: number;
  embedded: number;
}

export interface IndexState {
  snapshot_id: string | null;
  status: SnapshotStatus | null;
  stage: SnapshotStage | null;
  stage_title: string | null;
  commit_sha: string | null;
  started_at: string | null;
  finished_at: string | null;
  failure_reason: string | null;
  is_ready: boolean;
  is_embedding: boolean;
  embedding_backend: string;
  embedding_stopped: boolean;
  context_ready: boolean;
  vectors: VectorCoverage;
  totals: IndexTotals;
  stats: IndexStats | null;
}

export interface EmbedderChoice {
  key: string;
  title: string;
  note: string;
  vector_set: string;
}

export interface IndexTotals {
  files: number;
  symbols: number;
  chunks: number;
  edges: number;
}

export type StepKind =
  | "stage"
  | "thought"
  | "tool_call"
  | "tool_result"
  | "answer"
  | "fallback";

export interface InvestigationStep {
  cursor: number;
  file_path: string;
  number: number;
  kind: StepKind;
  tool_name: string | null;
  arguments: string | null;
  detail: string;
  duration_ms: number;
  is_error: boolean;
}

export interface Investigation {
  steps: InvestigationStep[];
  next_cursor: number;
}

export interface ResolvedRevision {
  revision: string;
  commit_sha: string;
  subject: string | null;
}

export type ChatRole = "user" | "assistant" | "tool";

export interface ToolCall {
  call_id: string;
  name: string;
  arguments: string;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  created_at: string;
  tool_calls: ToolCall[];
  tool_name: string | null;
  model: string | null;
  tokens_input: number;
  tokens_output: number;
}

export interface AttachedDocument {
  name: string;
  size: number;
}

export interface Conversation {
  id: string;
  repository_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  document: AttachedDocument | null;
  messages: ChatMessage[];
}

export type ChatEventKind =
  | "token"
  | "tool_call"
  | "tool_result"
  | "note"
  | "answer"
  | "failure";

export interface ChatEvent {
  kind: ChatEventKind;
  text: string;
  tool_name: string | null;
  tool_arguments: string | null;
  tool_call_id: string | null;
  model: string | null;
  tokens_input: number;
  tokens_output: number;
}


export type TenantRole = "owner" | "member";

export interface Organization {
  id: string;
  slug: string;
  name: string;
  created_at: string;
}

export interface Member {
  id: string;
  email: string;
  role: TenantRole;
  created_at: string;
  last_seen_at: string | null;
}

/** Кто вошёл. Организации может не быть — это состояние, а не ошибка. */
export interface CurrentUser {
  email: string;
  subject: string;
  organization: Organization | null;
  member: Member | null;
  /** Видит журнал установки: право не зависит от организации. */
  is_installation_admin: boolean;
}

export type LogLevel = "debug" | "info" | "warning" | "error" | "critical";

/** Одна строка журнала; в `fields` — контекст события, свой у каждого. */
export interface LogRecord {
  timestamp: string | null;
  level: string | null;
  logger: string | null;
  event: string;
  exception: string | null;
  fields: Record<string, unknown>;
}

export interface LogTail {
  file: string;
  size_bytes: number;
  scanned_lines: number;
  /** Строки, не разобранные как JSON: в файл писал кто-то ещё или он повреждён. */
  skipped_lines: number;
  /** Отбор остановлен по лимиту — раньше в файле есть ещё подходящие записи. */
  truncated: boolean;
  records: LogRecord[];
}

export interface LogFilter {
  limit: number;
  level: LogLevel | null;
  logger: string;
  q: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: TenantRole;
  created_at: string;
  expires_at: string;
}

/** Приглашение вместе с секретом: он показывается ровно один раз. */
export interface IssuedInvitation extends Invitation {
  token: string;
}


export interface ProviderConnection {
  id: string;
  name: string;
  default_model: string;
  models: string[];
  catalogue_refreshed_at: string | null;
  provider: string;
  base_url: string;
  trust: ModelTrust;
  supports_tools: boolean;
  context_window: number;
  note: string;
  is_enabled: boolean;
  has_api_key: boolean;
  created_at: string;
}

/** Известный провайдер с заполненными полями и адресом, где выдают ключ. */
export interface ModelPreset {
  key: string;
  title: string;
  model: string;
  provider: string;
  base_url: string;
  trust: ModelTrust;
  supports_tools: boolean;
  context_window: number;
  signup_url: string;
  pricing: string;
  note: string;
}

export interface AddConnectionPayload {
  name: string;
  api_key: string;
  default_model: string;
  catalogue: string[];
  provider: string;
  base_url: string;
  trust: ModelTrust;
  supports_tools: boolean;
  context_window: number;
  note: string;
}


export interface ProbeResult {
  is_reachable: boolean;
  detail: string;
  models: string[];
}
