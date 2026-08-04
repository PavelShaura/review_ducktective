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

export type EgressPolicy = "local_only" | "allow_cloud";

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

export type SnapshotStage = "parsing" | "storing" | "linking" | "embedding";

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
  embedding_stopped: boolean;
  context_ready: boolean;
  vectors: VectorCoverage;
  stats: IndexStats | null;
}
