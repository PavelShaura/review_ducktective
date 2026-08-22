import type {
  Conversation,
  DiffSide,
  Feedback,
  FeedbackDigest,
  FeedbackVerdict,
  FileContext,
  FilePatch,
  IndexState,
  Investigation,
  Repository,
  ResolvedRevision,
  ReviewRun,
  ReviewRunSummary,
} from "@/api/types";

const TENANT_ID = import.meta.env.VITE_TENANT_ID ?? "11111111-1111-1111-1111-111111111111";

/** Разговор, в который попал человек, и завели ли его сейчас. */
export interface StartedConversation {
  conversation: Conversation;
  isNew: boolean;
}

export interface ContextWindow {
  side: DiffSide;
  startLine: number;
  endLine: number;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }
  return (await response.json()) as T;
}

/** Ответ вместе с кодом: им сервер отличает заведённое от возвращённого. */
async function requestWithStatus<T>(
  path: string,
  init?: RequestInit,
): Promise<{ data: T; status: number }> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }
  return { data: (await response.json()) as T, status: response.status };
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

export const api = {
  tenantId: TENANT_ID,

  listRepositories: () =>
    request<Repository[]>(`/repositories?tenant_id=${TENANT_ID}`),

  registerRepository: (localPath: string, name: string, allowCloud: boolean) =>
    request<Repository>("/repositories", {
      method: "POST",
      body: JSON.stringify({
        tenant_id: TENANT_ID,
        name,
        vcs_provider: "local",
        local_path: localPath,
        egress_policy: allowCloud ? "allow_cloud" : "local_only",
      }),
    }),

  deleteRepository: async (repositoryId: string): Promise<void> => {
    const response = await fetch(`/api/repositories/${repositoryId}?tenant_id=${TENANT_ID}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new ApiError(response.status, response.statusText);
    }
  },

  listRuns: (repositoryId: string) =>
    request<ReviewRunSummary[]>(`/repositories/${repositoryId}/reviews?tenant_id=${TENANT_ID}`),

  getRun: (runId: string) => request<ReviewRun>(`/reviews/${runId}?tenant_id=${TENANT_ID}`),

  deleteRun: async (runId: string): Promise<void> => {
    const response = await fetch(`/api/reviews/${runId}?tenant_id=${TENANT_ID}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new ApiError(response.status, response.statusText);
    }
  },

  cancelRun: (runId: string) =>
    request<{ cancelled: boolean }>(`/reviews/${runId}/cancel?tenant_id=${TENANT_ID}`, {
      method: "POST",
    }),

  restartRun: (runId: string) =>
    request<ReviewRun>(`/reviews/${runId}/restart?tenant_id=${TENANT_ID}`, { method: "POST" }),

  resumeRun: (runId: string) =>
    request<ReviewRun>(`/reviews/${runId}/resume?tenant_id=${TENANT_ID}`, { method: "POST" }),

  getFilePatch: (runId: string, fileId: string) =>
    request<FilePatch>(`/reviews/${runId}/files/${fileId}/patch?tenant_id=${TENANT_ID}`),

  getFileContext: (runId: string, fileId: string, window: ContextWindow) =>
    request<FileContext>(
      `/reviews/${runId}/files/${fileId}/content?tenant_id=${TENANT_ID}` +
        `&side=${window.side}&start_line=${window.startLine}&end_line=${window.endLine}`,
    ),

  getIndexState: (repositoryId: string) =>
    request<IndexState>(`/repositories/${repositoryId}/index?tenant_id=${TENANT_ID}`),

  resolveRevision: (repositoryId: string, revision: string) =>
    request<ResolvedRevision>(
      `/repositories/${repositoryId}/revision?tenant_id=${TENANT_ID}` +
        `&revision=${encodeURIComponent(revision)}`,
    ),

  startIndexing: (repositoryId: string, revision = "HEAD") =>
    request<{ queued: boolean; revision: string }>(`/repositories/${repositoryId}/index`, {
      method: "POST",
      body: JSON.stringify({ tenant_id: TENANT_ID, revision }),
    }),

  cancelIndexing: (repositoryId: string) =>
    request<{ cancelled: boolean }>(
      `/repositories/${repositoryId}/index/cancel?tenant_id=${TENANT_ID}`,
      { method: "POST" },
    ),

  deleteIndex: (repositoryId: string) =>
    request<{ removed_snapshots: number }>(
      `/repositories/${repositoryId}/index?tenant_id=${TENANT_ID}`,
      { method: "DELETE" },
    ),

  getFeedbackDigest: (repositoryId: string) =>
    request<FeedbackDigest>(`/repositories/${repositoryId}/feedback?tenant_id=${TENANT_ID}`),

  startReview: (repositoryId: string, base: string, head: string) =>
    request<ReviewRun>(`/repositories/${repositoryId}/reviews`, {
      method: "POST",
      body: JSON.stringify({ tenant_id: TENANT_ID, base, head }),
    }),

  enqueueReview: (runId: string) =>
    request<ReviewRun>(`/reviews/${runId}/run?tenant_id=${TENANT_ID}`, { method: "POST" }),

  listConversations: (repositoryId: string) =>
    request<Conversation[]>(
      `/chat/conversations?repository_id=${repositoryId}&tenant_id=${TENANT_ID}`,
    ),

  startConversation: async (repositoryId: string): Promise<StartedConversation> => {
    const { data, status } = await requestWithStatus<Conversation>(`/chat/conversations`, {
      method: "POST",
      body: JSON.stringify({ repository_id: repositoryId, tenant_id: TENANT_ID }),
    });
    return { conversation: data, isNew: status === 201 };
  },

  attachDocument: (conversationId: string, name: string, text: string) =>
    request<Conversation>(
      `/chat/conversations/${conversationId}/document?tenant_id=${TENANT_ID}`,
      { method: "PUT", body: JSON.stringify({ name, text }) },
    ),

  detachDocument: (conversationId: string) =>
    request<Conversation>(
      `/chat/conversations/${conversationId}/document?tenant_id=${TENANT_ID}`,
      { method: "DELETE" },
    ),

  getConversation: (conversationId: string) =>
    request<Conversation>(`/chat/conversations/${conversationId}?tenant_id=${TENANT_ID}`),

  deleteConversation: async (conversationId: string): Promise<void> => {
    const response = await fetch(`/api/chat/conversations/${conversationId}?tenant_id=${TENANT_ID}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new ApiError(response.status, response.statusText);
    }
  },

  chatStream: (conversationId: string): WebSocket => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    return new WebSocket(
      `${scheme}://${window.location.host}/api/chat/conversations/${conversationId}` +
        `/stream?tenant_id=${TENANT_ID}`,
    );
  },

  investigationStream: (runId: string): WebSocket => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    return new WebSocket(
      `${scheme}://${window.location.host}/api/reviews/${runId}` +
        `/investigation/stream?tenant_id=${TENANT_ID}`,
    );
  },

  getInvestigation: (runId: string, after = 0) =>
    request<Investigation>(
      `/reviews/${runId}/investigation?tenant_id=${TENANT_ID}&after=${after}`,
    ),

  submitFeedback: (runId: string, findingId: string, verdict: FeedbackVerdict) =>
    request<Feedback>(`/reviews/${runId}/findings/${findingId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ tenant_id: TENANT_ID, verdict }),
    }),
};
