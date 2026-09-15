import type {
  EmbedderChoice,
  AddConnectionPayload,
  AvailableModel,
  Conversation,
  CurrentUser,
  DiffSide,
  EgressPolicy,
  Feedback,
  FeedbackDigest,
  FeedbackVerdict,
  FileContext,
  FilePatch,
  IndexState,
  Investigation,
  Invitation,
  IssuedInvitation,
  LogFilter,
  LogTail,
  Member,
  ModelPreset,
  Organization,
  ProbeResult,
  ProviderConnection,
  Repository,
  ResolvedRevision,
  ReviewRun,
  ReviewRunSummary,
} from "@/api/types";
import { accessToken } from "@/api/token";

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

/** Заголовки запроса вместе с токеном: организация выясняется по нему, а не по параметру. */
function headers(extra?: HeadersInit): HeadersInit {
  const token = accessToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: headers(init?.headers),
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
    headers: headers(init?.headers),
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }
  return { data: (await response.json()) as T, status: response.status };
}

/**
 * Запрос без тела ответа: удаление отвечает `204`, и разбирать там нечего.
 *
 * Отдельной функцией, а не голым `fetch` в каждой ручке: три таких вызова
 * когда-то написали до появления входа, и все три остались без заголовка
 * с токеном — удаление перестало работать ровно тогда, когда появилась
 * авторизация.
 */
async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: headers(init?.headers),
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

/**
 * Сокет, представляющийся первым сообщением.
 *
 * Токен не кладётся в адрес: адрес целиком пишется в журналы сервера
 * и прокси. Заголовков у браузерного `WebSocket` нет, поэтому первым уходит
 * сообщение с токеном, и только после него — вопросы.
 *
 * Отправка висит слушателем, а не на `onopen`: вызывающий присваивает `onopen`
 * себе, и назначение затёрло бы представление сокета. Слушатель зарегистрирован
 * раньше, поэтому токен и уходит первым.
 */
function authenticatedSocket(path: string): WebSocket {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${window.location.host}${path}`);
  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({ token: accessToken() ?? "" }));
  });
  return socket;
}

export const api = {
  listRepositories: () =>
    request<Repository[]>(`/repositories`),

  registerRepository: (localPath: string, name: string, egressPolicy: EgressPolicy) =>
    request<Repository>("/repositories", {
      method: "POST",
      body: JSON.stringify({
        name,
        vcs_provider: "local",
        local_path: localPath,
        egress_policy: egressPolicy,
      }),
    }),

  listModels: (repositoryId: string) =>
    request<AvailableModel[]>(`/repositories/${repositoryId}/models`),

  deleteRepository: (repositoryId: string) =>
    requestVoid(`/repositories/${repositoryId}`, { method: "DELETE" }),

  listRuns: (repositoryId: string) =>
    request<ReviewRunSummary[]>(`/repositories/${repositoryId}/reviews`),

  getRun: (runId: string) => request<ReviewRun>(`/reviews/${runId}`),

  deleteRun: (runId: string) => requestVoid(`/reviews/${runId}`, { method: "DELETE" }),

  cancelRun: (runId: string) =>
    request<{ cancelled: boolean }>(`/reviews/${runId}/cancel`, {
      method: "POST",
    }),

  restartRun: (runId: string) =>
    request<ReviewRun>(`/reviews/${runId}/restart`, { method: "POST" }),

  resumeRun: (runId: string) =>
    request<ReviewRun>(`/reviews/${runId}/resume`, { method: "POST" }),

  getFilePatch: (runId: string, fileId: string) =>
    request<FilePatch>(`/reviews/${runId}/files/${fileId}/patch`),

  getFileContext: (runId: string, fileId: string, window: ContextWindow) =>
    request<FileContext>(
      `/reviews/${runId}/files/${fileId}/content` +
        `&side=${window.side}&start_line=${window.startLine}&end_line=${window.endLine}`,
    ),

  getIndexState: (repositoryId: string) =>
    request<IndexState>(`/repositories/${repositoryId}/index`),

  resolveRevision: (repositoryId: string, revision: string) =>
    request<ResolvedRevision>(
      `/repositories/${repositoryId}/revision` +
        `?revision=${encodeURIComponent(revision)}`,
    ),

  startIndexing: (repositoryId: string, revision = "HEAD", embeddingBackend?: string) =>
    request<{ queued: boolean; revision: string }>(`/repositories/${repositoryId}/index`, {
      method: "POST",
      body: JSON.stringify({ revision, embedding_backend: embeddingBackend ?? null }),
    }),

  listEmbedders: () => request<EmbedderChoice[]>("/repositories/embedders"),

  cancelIndexing: (repositoryId: string) =>
    request<{ cancelled: boolean }>(
      `/repositories/${repositoryId}/index/cancel`,
      { method: "POST" },
    ),

  deleteIndex: (repositoryId: string) =>
    request<{ removed_snapshots: number }>(
      `/repositories/${repositoryId}/index`,
      { method: "DELETE" },
    ),

  getFeedbackDigest: (repositoryId: string) =>
    request<FeedbackDigest>(`/repositories/${repositoryId}/feedback`),

  startReview: (repositoryId: string, base: string, head: string, model?: string) =>
    request<ReviewRun>(`/repositories/${repositoryId}/reviews`, {
      method: "POST",
      body: JSON.stringify({ base, head, model: model ?? null }),
    }),

  enqueueReview: (runId: string) =>
    request<ReviewRun>(`/reviews/${runId}/run`, { method: "POST" }),

  listConversations: (repositoryId: string) =>
    request<Conversation[]>(
      `/chat/conversations?repository_id=${repositoryId}`,
    ),

  startConversation: async (
    repositoryId: string,
    model?: string,
  ): Promise<StartedConversation> => {
    const { data, status } = await requestWithStatus<Conversation>(`/chat/conversations`, {
      method: "POST",
      body: JSON.stringify({ repository_id: repositoryId, model: model ?? null }),
    });
    return { conversation: data, isNew: status === 201 };
  },

  attachDocument: (conversationId: string, name: string, text: string) =>
    request<Conversation>(
      `/chat/conversations/${conversationId}/document`,
      { method: "PUT", body: JSON.stringify({ name, text }) },
    ),

  detachDocument: (conversationId: string) =>
    request<Conversation>(
      `/chat/conversations/${conversationId}/document`,
      { method: "DELETE" },
    ),

  getConversation: (conversationId: string) =>
    request<Conversation>(`/chat/conversations/${conversationId}`),

  deleteConversation: (conversationId: string) =>
    requestVoid(`/chat/conversations/${conversationId}`, { method: "DELETE" }),

  chatStream: (conversationId: string): WebSocket =>
    authenticatedSocket(`/api/chat/conversations/${conversationId}/stream`),

  investigationStream: (runId: string): WebSocket =>
    authenticatedSocket(`/api/reviews/${runId}/investigation/stream`),

  getInvestigation: (runId: string, after = 0) =>
    request<Investigation>(
      `/reviews/${runId}/investigation?after=${after}`,
    ),

  getCurrentUser: () => request<CurrentUser>("/auth/me"),

  tailLogs: (filter: LogFilter) => {
    const params = new URLSearchParams({ limit: String(filter.limit) });
    if (filter.level) params.set("level", filter.level);
    if (filter.logger.trim()) params.set("logger", filter.logger.trim());
    if (filter.q.trim()) params.set("q", filter.q.trim());
    return request<LogTail>(`/admin/logs?${params.toString()}`);
  },

  listConnections: () => request<ProviderConnection[]>("/organization/models"),

  listModelPresets: () => request<ModelPreset[]>("/organization/models/presets"),

  probeConnection: (payload: {
    model: string;
    api_key?: string;
    provider?: string;
    base_url?: string;
  }) =>
    request<ProbeResult>("/organization/models/probe", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  addConnection: (payload: AddConnectionPayload) =>
    request<ProviderConnection>("/organization/models", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  refreshCatalogue: (connectionId: string) =>
    request<ProviderConnection>(`/organization/models/${connectionId}/catalogue`, {
      method: "POST",
    }),

  updateConnection: (
    connectionId: string,
    payload: Partial<AddConnectionPayload> & { is_enabled?: boolean },
  ) =>
    request<ProviderConnection>(`/organization/models/${connectionId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  deleteConnection: (connectionId: string) =>
    requestVoid(`/organization/models/${connectionId}`, { method: "DELETE" }),

  createOrganization: (slug: string, name: string) =>
    request<Organization>("/organizations", {
      method: "POST",
      body: JSON.stringify({ slug, name }),
    }),

  listMembers: () => request<Member[]>("/organization/members"),

  changeMemberRole: (memberId: string, role: "owner" | "member") =>
    request<Member>(`/organization/members/${memberId}`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),

  removeMember: (memberId: string) =>
    requestVoid(`/organization/members/${memberId}`, { method: "DELETE" }),

  listInvitations: () => request<Invitation[]>("/organization/invitations"),

  inviteMember: (email: string, role: "owner" | "member") =>
    request<IssuedInvitation>("/organization/invitations", {
      method: "POST",
      body: JSON.stringify({ email, role }),
    }),

  revokeInvitation: (invitationId: string) =>
    requestVoid(`/organization/invitations/${invitationId}`, { method: "DELETE" }),

  acceptInvitation: (token: string) =>
    request<Member>("/invitations/accept", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  submitFeedback: (runId: string, findingId: string, verdict: FeedbackVerdict) =>
    request<Feedback>(`/reviews/${runId}/findings/${findingId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ verdict }),
    }),
};
