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

export interface ReviewRun {
  id: string;
  repository_id: string;
  source: string;
  status: ReviewStatus;
  base_sha: string;
  head_sha: string;
  totals: Record<string, number>;
  failure_reason: string | null;
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
}

export interface Feedback {
  id: string;
  verdict: FeedbackVerdict;
  comment: string | null;
  created_at: string;
}
