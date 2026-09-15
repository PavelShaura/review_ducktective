import type { Resource } from "@/i18n/resource";

/**
 * Английский словарь. Форма задана русским — см. `ru.ts`.
 *
 * Тон сохранён: интерфейс говорит языком детективной картотеки — «дела»,
 * «расследование», «архив», — и перевод держит ту же метафору, а не
 * сводит её к «tasks» и «jobs».
 */
export const en: Resource = {
  common: {
    serviceDown: "The service is not responding.",
    yes: "yes",
    no: "no",
    cancel: "cancel",
    collapse: "collapse",
    expandMore: "show +",
    collapseLess: "collapse −",
    showMore: "show more",
  },

  language: {
    label: "language",
    ru: "RU",
    en: "EN",
    title: "Interface language",
  },

  app: {
    tagline: "case files on code quality",
    loading: "opening the folder…",
    newReview: "+ new review",
    newReviewTitle: "Run a review of a diff",
    signOut: "sign out",
    signOutTitle: "Sign out of {{email}}",
    signOutTitleShort: "Sign out",
    notFoundTitle: "No such case in the archive",
    notFoundBack: "back to the list",
    nav: {
      cases: "reviews",
      casesTitle: "All review runs",
      chat: "chat",
      chatTitle: "Ask about the code in your own words",
      indexes: "indexes",
      indexesTitle: "What has been parsed, when, and how to rebuild it",
      models: "models",
      modelsTitle: "Connections to model providers",
      marks: "marks",
      marksTitle: "Card index of verdicts on findings",
      organization: "members",
      organizationTitle: "Organisation: members, roles and invitations",
      logs: "log",
      logsTitle: "Installation log: api and workers, administrators only",
    },
  },

  signIn: {
    checking: "checking your pass…",
    providerDown: "The identity provider is not responding",
    retry: "try again",
    title: "Case files are issued by pass",
    body: "Sign-in is confirmed by the identity provider. Your password stays with it — the application never sees or stores it.",
    signIn: "sign in",
  },

  format: {
    stagedRevision: "staged",
  },

  status: {
    queued: "queued",
    indexing: "indexing",
    running: "investigating",
    completed: "closed",
    failed: "failed",
    cancelled: "withdrawn",
  },

  severity: {
    critical: "critical",
    major: "major",
    minor: "minor",
    nitpick: "nitpick",
  },

  verdict: {
    useful: "confirmed",
    false_positive: "false lead",
    wontfix: "deferred",
  },

  category: {
    correctness: "correctness",
    security: "security",
    performance: "performance",
    style: "style",
    tests: "tests",
    architecture: "architecture",
    conventions: "conventions",
  },

  finding: {
    lines: "line {{start}}",
    linesRange: "lines {{start}}–{{end}}",
    type: "type: {{type}}",
    reviewer: "reviewer: {{reviewer}}",
    confirm: "Confirm",
    falsePositive: "False lead",
    defer: "Defer",
    confidence: "confidence {{percent}}%",
    saveFailed: "The verdict was not saved. Check that the service is reachable and try again.",
  },

  deleteCase: {
    failed: "could not delete",
    delete: "delete",
    confirm: "delete the case?",
    deleting: "deleting…",
  },

  deleteRepository: {
    ariaLabel: "Remove repository {{name}}",
    remove: "remove from archive",
    confirm: "together with its cases and index?",
    removing: "removing…",
  },

  conversations: {
    starting: "starting…",
    newConversation: "+ new conversation",
    reusedHint: "This conversation already exists and is still empty — ask your question there.",
    count: "conversations: {{count}}",
    empty: "No conversations yet. Start the first one — the history is kept.",
    untitled: "no question yet",
    delete: "delete conversation",
  },

  conversation: {
    thinking: "thinking about the answer…",
    emptyTitle: "The conversation is empty",
    emptyBody: "Ask about the code of {{repository}}.",
    tokens: "{{model}} · {{count}} tok.",
    notIndexed:
      "The repository is not indexed — the conversation relies on the index, and the agent has nothing to look at. Press “index” in the index block above.",
    reconnecting: "reconnecting — your question will follow",
    placeholder: "a question about the code of {{repository}}",
    answering: "answering…",
    ask: "ask",
  },

  toolTrail: {
    asking: "querying the codebase",
    calls: "codebase lookups",
  },

  tool: {
    searching: "looking…",
    search_code: "searches by meaning",
    get_definition: "reads a definition",
    find_callers: "checks who calls it",
    get_file_context: "looks at the surroundings",
    find_symbol: "looks up a symbol",
    read_file: "reads a file",
    list_files: "lists what is there",
    get_file_outline: "reads the file outline",
    describe_repository: "looks around",
    project_docs: "reads the documentation",
    search_document: "searches the document",
  },

  document: {
    tooLarge: "The file is over 400 KB — it looks like the wrong one.",
    label: "document",
    size: "{{size}} KB",
    detach: "detach",
    localOnly: "the conversation goes through the local model only",
    attaching: "attaching…",
    attach: "+ attach a document",
    formats: " - md, txt, html",
  },

  contextMark: {
    withContext: "with context · {{covered}} of {{total}}",
    notCounted: "context not tallied",
    collecting: "collecting context",
    noIndexTitle: "Build the index so the reviewer sees the surroundings",
    noIndex: "no index · diff only",
  },

  indexBadge: {
    queueing: "queueing…",
    build: "build index",
    indexing: "indexing",
    indexingStage: "indexing · {{stage}}",
    ready: "index ready",
    readyFiles_one: "index ready · {{count}} file",
    readyFiles_few: "index ready · {{count}} files",
    readyFiles_many: "index ready · {{count}} files",
    readyFiles_other: "index ready · {{count}} files",
    none: "no index",
  },

  modelPicker: {
    label: "model",
    default: "default",
    defaultLong: "default — the system will choose",
    noTools: " · no tools",
    trainingShort: "definitely trains on requests: the code stays with the provider",
    trainingLong:
      "This model definitely trains on requests: the code goes to the provider and stays there.",
    remoteShort: "the code goes to the provider: its no-training promise is its word, not a guarantee",
    remoteLong:
      "The code goes to the provider. It promises not to train on requests, but that is its word, not a guarantee: for closed code only a local model is safe.",
    onlyLocal:
      "Only the local model is available — the repository policy keeps the code in, or no remote models are set up.",
    trust: {
      local: "code never leaves the machine",
      private_remote: "code goes to the provider · may train",
      training_remote: "code goes to the provider · definitely trains",
    },
  },

  repositoryPicker: {
    label: "repository",
    chooseFromList: "choose from the list",
    addByPath: "+ add by path",
    choose: "— choose a repository —",
    pathLabel: "path to the repository",
    pathHint:
      "A path on the machine running the service, not on yours — if the API runs in a container, the directory must be mounted inside.",
    nameLabel: "name",
    egressLegend: "where the code is allowed to go",
    egress: {
      local_only: {
        title: "Local model only",
        explanation:
          "The code never leaves the machine. The only safe option for closed code and code under NDA.",
      },
      allow_cloud: {
        title: "Remote models that promise not to train",
        explanation:
          "The code goes to the provider. Its promise not to store requests or train on them is its word, not a guarantee.",
      },
      allow_training_cloud: {
        title: "Any remote model, free tiers included",
        explanation:
          "Free tiers definitely log requests and train on them. Open code and experiments only.",
      },
    },
  },

  investigation: {
    title: "investigation",
    steps: "steps: {{count}}",
    now: "now: ",
    loading: "pulling the case materials…",
    ms: "{{value}} ms",
    kind: {
      stage: "stage",
      thought: "thinking",
      tool_call: "query",
      tool_result: "result",
      answer: "done",
      fallback: "no tools",
    },
  },

  fileDiff: {
    change: {
      added: "added",
      modified: "modified",
      deleted: "deleted",
      renamed: "renamed",
    },
    findings: "findings {{count}}",
    tooLarge:
      "The file is too large to display. Its findings are collected below; the diff itself is easier to read in an editor.",
    fileFindings: "Findings for the file",
    reading: "reading the file…",
    patchFailed: "Could not fetch the diff of this file.",
    toEnd: "to the end of the file",
    contextFailed: "Could not read the file at this revision — context not expanded.",
    outside: "Findings outside the shown lines",
    show: "show {{count}}",
    above: "{{count}} above",
    below: "{{count}} below",
    all: "all {{count}}",
  },

  index: {
    label: "index",
    cancelled: "The last build was cancelled — what was written has been rolled back",
    cancelledReady: ", reviews use the previous index.",
    cancelledNone: ", there is no index.",
    nothingToCancel: "Nothing to cancel — the build had already finished.",
    removed:
      "Index erased: {{count}} snapshot(s) removed. Rebuild it so reviews see the surroundings again.",
    embeddingStopped:
      "Vector computation stopped — what was computed is kept, the rest will follow on the next build. Semantic search is incomplete for now.",
    inQueue: "queued…",
    building: "building…",
    embedding: "computing vectors…",
    queueing: "queueing…",
    refresh: "refresh",
    build: "index",
    embedderLabel: "vectors computed by",
    deleteIndex: "delete index",
    deleteConfirm: "erase the whole index?",
    deleting: "erasing…",
    delete: "erase",
    cancelling: "cancelling…",
    cancelAction: "cancel",
    defaultStage: "parsing files",
    stageTitle: {
      parsing: "parsing files",
      storing: "storing symbols and fragments",
      linking: "building the link graph",
      embedding: "computing vectors",
      complete: "ready",
    },
    progressOf: " · {{done}} of {{total}} · {{percent}}%",
    stageNote: {
      parsing: "reading changed files and splitting them into symbols",
      storing: "writing symbols and fragments to the database in batches of 200 files",
      linking: "linking calls to definitions across the codebase",
      embedding: "computing vectors for semantic search — talks to the model",
    },
    vectors: "symbols and graph ready · vectors {{embedded}} of {{chunks}} · {{percent}}%",
    stalled: " · computation stopped",
    idle: " · not computing",
    layers:
      "The index has two layers. The first — symbols and the call graph — is ready: with it a review can tell who calls the changed code and what covers those lines. The second — vectors — gives semantic search for places named differently from the query. ",
    stalledAdvice:
      "The computation broke off and will not resume on its own: fix access to the model and rebuild the index — what was computed is kept, only the rest will run.",
    idleAdvice:
      "Vectors for the current model are missing — they were computed by another model or the computation was not finished. Press “refresh”: what was computed is kept, only the rest will run.",
    embeddingAdvice:
      "While vectors are being computed, reviews rely on words and the graph: they work, but find similar places less well.",
    queuedEmbedding: "The worker is finishing vectors from the previous build — the job will follow.",
    queued: "The job is queued. If it does not move, the indexing worker is not running: ",
    queuedBehind: "Queued behind {{name}} — that build has been running for {{duration}}. Position: {{position}}.",
    queuedBehindUnknown: "Queued behind a build of another repository. Position: {{position}}.",
    queuedBehindHint:
      "The worker takes one build at a time; cancel the one you do not need in its panel and the queue moves.",
    elapsed: " · running for {{duration}}",
    describe: {
      queueing: "queueing",
      waitingWorker: "waiting for a worker",
      building: "building",
      failed: "the last attempt failed",
      previous_one: "previous index · {{count}} file",
      previous_few: "previous index · {{count}} files",
      previous_many: "previous index · {{count}} files",
      previous_other: "previous index · {{count}} files",
      notBuilt: "not built — the review will go by the diff alone, without context",
      builtAt: " · built {{date}}",
      summary_one: "{{count}} file · revision {{sha}}",
      summary_few: "{{count}} files · revision {{sha}}",
      summary_many: "{{count}} files · revision {{sha}}",
      summary_other: "{{count}} files · revision {{sha}}",
    },
  },

  duration: {
    seconds: "{{count}} s",
    minutes: "{{count}} min",
    minutesSeconds: "{{minutes}} min {{seconds}} s",
    hoursMinutes: "{{hours}} h {{minutes}} min",
  },

  review: {
    stage: {
      build_context: "context",
      plan_review: "plan",
      review: "review",
      aggregate: "merge",
      verify: "verify",
    },
    kind: {
      context_overflow: "did not fit the window",
      output_exhausted: "answer cut off",
      invalid_output: "answer not parsed",
      timeout: "no answer in time",
      rate_limited: "rate limited",
      provider_unavailable: "model unavailable",
      context_unavailable: "context not collected",
      unknown: "failure",
    },
    limit: {
      window: "window {{value}}",
      answer: "answer {{value}}",
      timeout: "timeout {{value}} s",
    },
    advice: {
      context_overflow:
        "The prompt did not fit the model's context window. Raise the window (n_ctx) to 16384 — less is not enough for a review — or lower CONTEXT_TOKEN_BUDGET in .env, giving up context from the index.",
      output_exhausted:
        "The model used up its whole answer budget and did not finish. Space for the answer is reserved inside the window: the system prompt (~1300 tokens) + CONTEXT_TOKEN_BUDGET + LLM_MAX_OUTPUT_TOKENS are subtracted, and the remainder is all that is left for the diff. Raise the model window; if it thinks out loud, lowering LLM_MAX_OUTPUT_TOKENS will not help — the reasoning takes most of the answer.",
      timeout:
        "The model did not finish in the allotted time. Raise LLM_TIMEOUT_SECONDS in .env or take a lighter model: at 19 tokens per second one file takes two to three minutes.",
      rate_limited:
        "The provider limited the request rate. Wait and send the case for investigation again.",
      context_unavailable:
        "Context from the index could not be collected, and these files were read by the diff alone — quality on them is below usual. Check the repository index and rebuild it.",
    },
    indexWaiting: "the job is waiting for the indexing worker",
    indexBuilding: "building",
    titleIndexing: "Building the index at the case revision",
    titleRunning: "Investigation in progress",
    bodyIndexing:
      "The index was built at another revision, and a review with a foreign graph does worse than without one. Now: {{stage}}. The review starts right after.",
    bodyRunning:
      "The model reads {{count}} file(s) one by one. All findings appear at once when the run finishes.",
    elapsed: "running for",
    expected: "expected",
    about: "about {{duration}}",
    stopping: "stopping…",
    stop: "stop",
    cancelledTitle: "Investigation stopped",
    cancelledBody:
      "No findings were saved: they are all written at the end of the run. The diff is parsed and stays in place. Resume reads the files the run did not reach; restart reads them all.",
    resuming: "resuming…",
    resume: "resume",
    restarting: "reopening the case…",
    restart: "investigate again",
    actionFailed: "did not work — check that the service is up",
    degradedPartial: "The investigation was incomplete",
    degradedNoContext: "The investigation ran without context",
    failStamp: "failed",
    failedTitle: "The investigation failed",
    noReason: "The reason was not saved. Check the worker log — the details are there.",
    whatToDo: "what to do about it",
    promptUnknown:
      "Only the server names the prompt size, and only when it did not fit the window",
    table: {
      file: "file",
      who: "who",
      reason: "reason",
      model: "model",
      prompt: "prompt, tokens",
      limit: "hit",
    },
  },

  caseList: {
    loading: "browsing the archive…",
    unavailableTitle: "The archive is unavailable",
    unavailableBody:
      "The service is not responding. Start the API with ducktective serve and refresh the page.",
    emptyTitle: "The archive is empty",
    emptyBody:
      "No repository has been registered yet. Open a case — name the path to the repository and the revisions.",
    newCase: "open a case",
    localOnly: "local only",
    cloudAllowed: "cloud allowed",
    runsError:
      "The cases of this repository cannot be read: the service answered with an error. Check the API log — the cases are still there.",
    noRuns: "No cases for this repository yet.",
    clean: "clean",
    files: "files {{count}}",
  },

  case: {
    loading: "pulling the case materials…",
    notOpenTitle: "The case does not open",
    notOpenBody: "Check that the service is running and the case id is correct.",
    toList: "to the list of cases",
    noFileMatches: "No file matches this filter.",
    orphans: "findings without a file in the diff · {{count}}",
    label: "case",
    revisions: "revisions",
    files: "files",
    findings: "findings",
    createdAt: "opened",
    noFindings: "No findings — no problems in the changed lines.",
    all: "all {{count}}",
  },

  chat: {
    loading: "pulling the card index…",
    nothingToTalk: "Nothing to talk about yet: no repository has been registered.",
    repository: "repository",
    choose: "choose a repository",
    emptyTitle: "Chat about the codebase",
    emptyBody:
      "Ask in your own words. The agent searches by meaning, reads definitions, checks who calls what, and answers with links to files and lines. It answers from the index, that is, from a fixed revision.",
    openOrNew: "open a previous conversation on the left or start a new one",
    chooseLeft: "choose a repository on the left",
  },

  indexes: {
    loading: "pulling the card index…",
    title: "Indexes",
    intro:
      "An index is the parsed code of a repository: symbols, the call graph and vectors. With it a review sees the surroundings of the changed code, and a conversation answers with links to files and lines. Without one, a review works by the diff alone and finds half as much.",
    none: "No repository has been registered yet — add the first one and it can be indexed right away.",
    add: "+ add a repository",
    newTitle: "New repository",
    adding: "adding…",
    addAndIndex: "add and index",
    addOnly: "add only",
    conflict: "A repository with this name already exists.",
    revision: "revision {{sha}}",
    symbols: "{{count}} symbols",
    chunks: "{{count}} fragments",
    edges: "{{count}} links",
    details: "details",
  },

  onboarding: {
    title: "Open a case folder",
    intro:
      "Repositories, indexes and findings belong to an organisation. Create your own or accept an invitation to someone else's.",
    ownTitle: "Your own organisation",
    name: "name",
    namePlaceholder: "Engineering",
    slug: "short name",
    creating: "creating…",
    create: "create",
    invitationTitle: "Invitation",
    invitationBody: "The link is issued to your email address and is valid for a week.",
    code: "invitation code",
    codePlaceholder: "paste the code from the link",
    checking: "checking…",
    accept: "accept",
    notFound: "The invitation was not found or is no longer valid.",
    wrongEmail: "The invitation was issued to a different email address.",
  },

  organization: {
    role: {
      owner: "owner",
      member: "member",
    },
    loading: "pulling the organisation file…",
    fallbackName: "Organisation",
    youAre: " · you are {{role}}",
    members: "Members",
    lastSeen: " · seen {{date}}",
    makeMember: "make member",
    makeOwner: "make owner",
    exclude: "remove",
    invitations: "Invitations",
    email: "email address",
    issuing: "issuing…",
    invite: "invite",
    validUntil: "valid until {{date}}",
    revoke: "revoke",
    nobody: "No one is expected.",
    tokenFor: "code for {{email}} — shown only now",
    tokenBody:
      "Pass it along with the sign-in link. It cannot be shown again — only a fingerprint is stored.",
    conflict: "That would leave the organisation without an owner — or the invitation already exists.",
  },

  marks: {
    loading: "pulling the card index…",
    unavailable: "The service is not responding — the card index of marks is unavailable.",
    nothing: "Nothing to mark yet: no repository has been registered.",
    title: "Card index of marks",
    intro:
      "Everything you marked on finding cards. These marks form the evaluation set: the share of confirmed findings is the precision against which the next reviewer versions will be compared.",
    noneMarked:
      "No finding in this repository has been marked yet. Marks are set with the buttons on a finding card inside a case.",
    marked: "marked",
    of: "of",
    usefulShare: "share confirmed",
    caseLabel: "case {{sha}}",
  },

  newCase: {
    title: "New review",
    intro:
      "Name the repository and what to review: a whole commit or a range of revisions. A background worker runs it; the page refreshes itself.",
    commit: "commit",
    commitPlaceholder: "784418ca23a or HEAD",
    fromRevision: "from revision",
    toRevision: "to revision",
    starting: "starting the review…",
    start: "start the review",
    indexHint: "Index the project.",
    adding: "adding…",
    addRepository: "add repository",
    startFailed: "Could not start the review. Check that the API and the worker are running.",
    conflict: "A repository with this name already exists — choose it from the list.",
    noChanges: "There are no changes between these revisions.",
    rebuilding:
      "The index is being rebuilt — this does not affect the investigation. Context comes from the previous build; the new one is picked up by later cases.",
    building:
      "The index is still building and there is no context yet: the investigation will go by the diff alone and find noticeably less. Wait for the build to finish if completeness matters.",
    stale:
      "The review will run on {{wanted}}{{alias}}, but the index was built at {{indexed}}. The tools will read the right commit through git — without the call graph. ",
    queueing: "queueing…",
    indexRevision: "index {{sha}}",
    modeCommit: "single commit",
    modeRange: "revision range",
  },

  models: {
    trust: {
      local: "local · code never leaves the machine",
      private_remote: "code goes to the provider · may train",
      training_remote: "code goes to the provider · definitely trains",
    },
    trustShort: {
      local: "local",
      private_remote: "may train",
      training_remote: "trains",
    },
    loading: "pulling the model card index…",
    title: "Models",
    intro:
      "The local model is configured on the server and always available. Remote ones come as connections: one key — all models of the provider, and any of them can be chosen when starting a review or a conversation. The key is stored encrypted and never shown again.",
    addTitle: "Add a connection",
    none: "No connections — reviews and conversations run on the local model.",
    modelCount_one: "one model",
    modelCount_few: "{{count}} models",
    modelCount_many: "{{count}} models",
    modelCount_other: "{{count}} models",
    default: "default {{model}}",
    keySet: "key set",
    noKey: "no key",
    window: "window {{value}}",
    catalogueFrom: "catalogue from {{date}}",
    hideModels: "hide models",
    showModels: "show models ({{count}})",
    askingProvider: "asking the provider…",
    refreshCatalogue: "refresh catalogue",
    disable: "disable",
    enable: "enable",
    remove: "remove",
    asInPicker: "this is how they appear when choosing a model for a review or a conversation",
    isDefault: "default",
    choose: "choose",
    statusOff: "disabled",
    needsKey: "needs a key",
    connected: "connected",
    getKey: "get a key",
    keyLabel: "key — stored encrypted and never shown again",
    keyPlaceholder: "paste the provider key",
    defaultModelOffered: "default model — the provider offered {{count}}",
    probe: "check",
    adding: "adding…",
    connect: "connect",
    hideDetails: "hide details",
    manual: "configure manually",
    nameLabel: "connection name — models are listed under it in the picker",
    defaultModel: "default model",
    baseUrl: "server address, if non-standard",
    providerDown: "The provider did not answer: {{detail}}",
    probeAnswered: "The model answered",
    probeListed: "The provider answered, models available: {{count}}",
    allInPicker: " — all of them will appear in the picker for reviews and conversations",
  },

  presets: {
    "opencode-zen": {
      title: "OpenCode Zen",
      pricing: "free",
      note: "Free gateway models. The key is issued without payment details; some models train on requests while they are free",
    },
    "opencode-go": {
      title: "OpenCode Go (subscription)",
      pricing: "subscription, from $10 a month",
      note: "A subscription to open models. The limit is in dollars, not in request counts — for a conversation that matters more: the loop spends a request per step. The code goes to the provider; most models promise zero retention and no training, exceptions are named in their description",
    },
    "openrouter-free": {
      title: "OpenRouter, free route",
      pricing: "free",
      note: "About 50 requests a day without a deposit. An agentic run over ten files does not fit that limit — fine for a single diff",
    },
    groq: {
      title: "Groq",
      pricing: "free tier",
      note: "Fast answers, a daily token limit",
    },
    gemini: {
      title: "Google AI Studio",
      pricing: "free tier",
      note: "A large window and a generous free tier; requests are used to improve the models",
    },
    cerebras: {
      title: "Cerebras",
      pricing: "free tier",
      note: "A free tier with a daily token limit",
    },
    anthropic: {
      title: "Anthropic",
      pricing: "per token",
      note: "A paid provider: it promises not to train on requests, but the code leaves the machine",
    },
    compatible: {
      title: "Your own OpenAI-compatible server",
      pricing: "your own server",
      note: "A gateway or a server on your network: give the address with the /v1 suffix",
    },
  },

  logs: {
    title: "Installation log",
    intro:
      "The latest records from the shared log file: api, review and indexing workers. Each line is a separate event with the context it happened in.",
    level: "level",
    levelAll: "all levels",
    levelFrom: "{{level}} and above",
    logger: "logger",
    search: "search in line",
    searchPlaceholder: "run_id, model, error text…",
    records: "records",
    liveOn: "● live",
    liveOff: "○ live",
    liveTitle: "Re-read the log every few seconds",
    reading: "reading…",
    refresh: "refresh",
    opening: "opening the log…",
    noMatch: "No record matches these conditions.",
    shown: "shown",
    truncated: " — there is more further back; narrow the conditions or raise the limit",
    skipped: "lines skipped as non-JSON: ",
    forbidden: "The log is available to installation administrators only.",
    unavailable: "Could not read the log: the API is not responding.",
    bytes: "{{value}} B",
    kilobytes: "{{value}} KB",
    megabytes: "{{value}} MB",
  },
};
