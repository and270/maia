// The dashboard can be served either at the root of its host (e.g.
// https://kanban.tilos.com/) or under a URL prefix when reverse-proxied
// (e.g. https://mission-control.tilos.com/hermes/). The Python backend
// injects ``window.__HERMES_BASE_PATH__`` into index.html based on the
// incoming ``X-Forwarded-Prefix`` header so the SPA can address its own
// ``/api/...`` and ``/dashboard-plugins/...`` URLs correctly without a
// rebuild. Empty string means "served at root".
function readBasePath(): string {
  if (typeof window === "undefined") return "";
  const raw = window.__HERMES_BASE_PATH__ ?? "";
  if (!raw) return "";
  // Normalise: ensure leading slash, strip trailing slash.
  const withLead = raw.startsWith("/") ? raw : `/${raw}`;
  return withLead.replace(/\/+$/, "");
}

export const HERMES_BASE_PATH = readBasePath();
const BASE = HERMES_BASE_PATH;

import type { DashboardTheme } from "@/themes/types";

// Ephemeral session token for protected endpoints.
// Injected into index.html by the server — never fetched via API.
declare global {
  interface Window {
    __HERMES_SESSION_TOKEN__?: string;
    __HERMES_BASE_PATH__?: string;
    __HERMES_DASHBOARD_AUTH_REQUIRED__?: boolean;
  }
}
let _sessionToken: string | null = null;
const SESSION_HEADER = "X-Hermes-Session-Token";
const SESSION_STORAGE_KEY = "maiaHermes.dashboardSessionToken";

export type DashboardAuthStatus = {
  auth_required: boolean;
  authenticated: boolean;
  token?: string;
  actor?: {
    id?: string;
    platform?: string | null;
    user_id?: string | null;
    user_name?: string | null;
  };
  roles?: string[];
  source?: string;
  expires_at?: number;
  capabilities?: Record<string, boolean>;
  modes?: {
    local_token?: boolean;
    trusted_header?: boolean;
    channel_token?: boolean;
  };
};

export type DashboardAccessRequest = {
  id: string;
  actor_key: string;
  actor?: {
    platform?: string;
    user_id?: string;
    user_name?: string;
  };
  status: "pending" | "approved" | "denied" | "revoked" | string;
  reason?: string;
  requested_at?: number;
  updated_at?: number;
  reviewed_at?: number;
  reviewed_by_key?: string;
  approved_roles?: string[];
  approved_teams?: string[];
  decision_note?: string;
  revocation_reason?: string;
};

export type DashboardAccessRevocation = {
  actor_key: string;
  revoked_at?: number;
  revoked_by_key?: string;
  reason?: string;
  removed_tokens?: number;
};

export type DashboardAccessResponse = {
  requests: DashboardAccessRequest[];
  revoked_users: DashboardAccessRevocation[];
};

export type DiscordGatewayAccessUser = {
  user_id: string;
  name?: string;
  roles?: string[];
  teams?: string[];
  /** True only when governance.users has an explicit role for this identity. */
  governed?: boolean;
};

export type DiscordGatewayAccessUsersResponse = {
  ok?: boolean;
  users: DiscordGatewayAccessUser[];
  /** Configured governance.role_hierarchy (fallback default set). */
  roles?: string[];
  /** Team names already referenced anywhere in governance. */
  teams?: string[];
};

export type GovernanceUser = {
  actor_key: string;
  platform: string;
  user_id: string;
  name: string;
  roles: string[];
  teams: string[];
  governed: boolean;
  gateway_allowed: boolean;
  file_access: GovernanceFileGrant[];
};

export type GovernanceFileGrant = {
  path: string;
  recursive: boolean;
  read: boolean;
  write: boolean;
  write_approval_roles?: string[];
  write_approval_users?: string[];
};

export type GovernanceSandboxStatus = {
  ready: boolean;
  mode: "full" | "restricted";
  status:
    | "ready"
    | "not_found"
    | "not_executable"
    | "daemon_timeout"
    | "daemon_unavailable"
    | "wsl_integration_disabled"
    | "unsupported_platform";
  platform: "windows_wsl" | "linux" | "macos" | "windows_native" | "android_termux" | "unknown";
  platform_label: string;
  distro: string;
  runtime: "docker" | "podman" | null;
  message: string;
  remediation: string;
  why: string;
  available_capabilities: string[];
  blocked_capabilities: string[];
  steps: Array<{
    title: string;
    detail: string;
    command?: string;
    url?: string;
  }>;
  can_auto_setup: boolean;
  setup_command: string;
  verify_command: string;
  docs_url: string;
};

export type GovernanceServerPathEntry = {
  name: string;
  path: string;
  kind: "directory" | "file";
};

export type GovernanceServerPathLocation = {
  label: string;
  path: string;
};

export type GovernanceServerPathsResponse = {
  current_path: string;
  parent_path: string | null;
  selected_path: string | null;
  breadcrumbs: GovernanceServerPathLocation[];
  locations: GovernanceServerPathLocation[];
  entries: GovernanceServerPathEntry[];
  truncated: boolean;
};

export type GovernanceTeam = {
  name: string;
  members: string[];
  file_access: GovernanceFileGrant[];
  delegated_root: {
    path: string;
    manager_roles?: string[];
    managers?: string[];
    [key: string]: unknown;
  } | null;
};

export type GovernanceOverview = {
  enabled: boolean;
  tenant_id: string;
  default_role: string;
  role_hierarchy: string[];
  team_file_manager_roles: string[];
  gateway: {
    group_sessions_per_user: boolean;
    thread_sessions_per_user: boolean;
  };
  cron: { default_authorizer_roles: string[] };
  terminal: { allowed_roles: string[]; approver_roles: string[] };
  teams: string[];
  team_records: GovernanceTeam[];
  users: GovernanceUser[];
};

export type FolderPolicy = {
  path: string;
  recursive?: boolean;
  label?: string;
  description?: string;
  roles?: string[];
  read_roles?: string[];
  write_roles?: string[];
  teams?: string[];
  read_teams?: string[];
  write_teams?: string[];
  deny_teams?: string[];
  users?: string[];
  read_users?: string[];
  write_users?: string[];
  deny_users?: string[];
  // Non-empty: every write under this policy is staged for approval by these
  // roles/users. Present-but-empty: explicit opt-out from an ancestor's
  // requirement.
  write_approval_roles?: string[];
  write_approval_users?: string[];
};

export type FolderPoliciesResponse = {
  enabled: boolean;
  folder_policies: FolderPolicy[];
  team_file_roots: Record<string, { path: string; [key: string]: unknown }>;
  actor: {
    teams: string[];
    can_admin: boolean;
    managed_teams: string[];
  };
};

export function isDashboardAuthRequired(): boolean {
  return Boolean(window.__HERMES_DASHBOARD_AUTH_REQUIRED__);
}

function readStoredSessionToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.sessionStorage.getItem(SESSION_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setDashboardSessionToken(token: string): void {
  _sessionToken = token || null;
  if (token) {
    window.__HERMES_SESSION_TOKEN__ = token;
  } else {
    delete window.__HERMES_SESSION_TOKEN__;
  }
  try {
    if (token) {
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, token);
    } else {
      window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
    }
  } catch {
    // sessionStorage can be disabled by policy; in-memory state still works.
  }
  window.dispatchEvent(new CustomEvent("maia-dashboard-authenticated"));
}

function setSessionHeader(headers: Headers, token: string): void {
  if (!headers.has(SESSION_HEADER)) {
    headers.set(SESSION_HEADER, token);
  }
}

export async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  // Inject the session token into all /api/ requests.
  const headers = new Headers(init?.headers);
  const token = window.__HERMES_SESSION_TOKEN__ || _sessionToken || readStoredSessionToken();
  if (token) {
    setSessionHeader(headers, token);
  }
  const res = await fetch(`${BASE}${url}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

async function getSessionToken(): Promise<string> {
  if (_sessionToken) return _sessionToken;
  const injected = window.__HERMES_SESSION_TOKEN__;
  if (injected) {
    _sessionToken = injected;
    return _sessionToken;
  }
  const stored = readStoredSessionToken();
  if (stored) {
    _sessionToken = stored;
    return _sessionToken;
  }
  throw new Error("Session token not available — page must be served by the Hermes dashboard server");
}

export const api = {
  getDashboardAuthStatus: () =>
    fetchJSON<DashboardAuthStatus>("/api/dashboard/auth/status"),
  loginDashboard: (token: string) =>
    fetchJSON<DashboardAuthStatus>("/api/dashboard/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    }),
  logoutDashboard: () =>
    fetchJSON<{ ok: boolean }>("/api/dashboard/auth/logout", { method: "POST" }),
  getDashboardAccessRequests: () =>
    fetchJSON<DashboardAccessResponse>("/api/dashboard/access/requests"),
  approveDashboardAccessRequest: (
    requestId: string,
    body: { roles: string[]; teams: string[]; name?: string; note?: string },
  ) =>
    fetchJSON<{ ok: boolean; request: DashboardAccessRequest }>(
      `/api/dashboard/access/requests/${encodeURIComponent(requestId)}/approve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  denyDashboardAccessRequest: (requestId: string, reason = "") =>
    fetchJSON<{ ok: boolean; request: DashboardAccessRequest }>(
      `/api/dashboard/access/requests/${encodeURIComponent(requestId)}/deny`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      },
    ),
  revokeDashboardAccess: (actor_key: string, reason = "") =>
    fetchJSON<{ ok: boolean; revocation: DashboardAccessRevocation; dropped_sessions: number }>(
      "/api/dashboard/access/revoke",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor_key, reason }),
      },
    ),
  restoreDashboardAccess: (actor_key: string) =>
    fetchJSON<{ ok: boolean }>("/api/dashboard/access/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor_key }),
    }),
  getFolderPolicies: () =>
    fetchJSON<FolderPoliciesResponse>("/api/governance/folder-policies"),
  saveFolderPolicies: (body: {
    folder_policies: FolderPolicy[];
  }) =>
    fetchJSON<{ ok: boolean; folder_policies: FolderPolicy[] }>(
      "/api/governance/folder-policies",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  applyGovernanceBaseline: (body?: {
    terminal_allowed_roles?: string[];
    terminal_approver_roles?: string[];
    smart_approvals?: boolean;
  }) =>
    fetchJSON<{
      ok: boolean;
      applied: Record<string, unknown>;
      warnings: GovernanceWarning[];
    }>("/api/onboarding/apply-governance-baseline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    }),
  getOnboardingState: () => fetchJSON<OnboardingState>("/api/onboarding/state"),
  getGovernanceOptions: () =>
    fetchJSON<{ roles: string[]; teams: string[] }>("/api/governance/options"),
  getGovernanceOverview: () =>
    fetchJSON<GovernanceOverview>("/api/governance/overview"),
  getSecureRuntimeStatus: () =>
    fetchJSON<GovernanceSandboxStatus>("/api/secure-runtime/status"),
  getGovernanceSandboxStatus: () =>
    fetchJSON<GovernanceSandboxStatus>("/api/secure-runtime/status"),
  browseGovernanceServerPaths: (path?: string) => {
    const query = path ? `?path=${encodeURIComponent(path)}` : "";
    return fetchJSON<GovernanceServerPathsResponse>(
      `/api/governance/server-paths${query}`,
    );
  },
  saveGovernanceUser: (
    actorKey: string,
    body: {
      name: string;
      roles: string[];
      teams: string[];
      file_access?: GovernanceFileGrant[];
    },
  ) =>
    fetchJSON<{ ok: boolean }>(
      `/api/governance/users/${encodeURIComponent(actorKey)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  removeGovernanceUser: (actorKey: string) =>
    fetchJSON<{ ok: boolean; removed: boolean }>(
      `/api/governance/users/${encodeURIComponent(actorKey)}`,
      { method: "DELETE" },
    ),
  createGovernanceTeam: (name: string) =>
    fetchJSON<{ ok: boolean; team: GovernanceTeam }>("/api/governance/teams", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  saveGovernanceTeam: (
    name: string,
    body: {
      members: string[];
      file_access: GovernanceFileGrant[];
      delegated_root: GovernanceTeam["delegated_root"];
    },
  ) =>
    fetchJSON<{ ok: boolean; team: GovernanceTeam }>(
      `/api/governance/teams/${encodeURIComponent(name)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  removeGovernanceTeam: (name: string) =>
    fetchJSON<{ ok: boolean; removed: string }>(
      `/api/governance/teams/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
  saveGovernanceSettings: (body: {
    tenant_id: string;
    default_role: string;
    role_hierarchy: string[];
    team_file_manager_roles: string[];
    gateway_group_sessions_per_user: boolean;
    gateway_thread_sessions_per_user: boolean;
    cron_default_authorizer_roles: string[];
    terminal_allowed_roles: string[];
    terminal_approver_roles: string[];
  }) =>
    fetchJSON<GovernanceOverview>("/api/governance/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  setReasoningEffort: (effort: string) =>
    fetchJSON<{ ok: boolean; effort: string }>("/api/model/effort", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ effort }),
    }),
  getGatewayAccessUsers: (platform: string) =>
    fetchJSON<DiscordGatewayAccessUsersResponse>(
      `/api/gateway/${encodeURIComponent(platform)}/access-users`,
    ),
  saveGatewayAccessUsers: (platform: string, body: { users: DiscordGatewayAccessUser[] }) =>
    fetchJSON<DiscordGatewayAccessUsersResponse>(
      `/api/gateway/${encodeURIComponent(platform)}/access-users`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  getStatus: () => fetchJSON<StatusResponse>("/api/status"),
  getSessions: (limit = 20, offset = 0) =>
    fetchJSON<PaginatedSessions>(`/api/sessions?limit=${limit}&offset=${offset}`),
  getSessionMessages: (id: string) =>
    fetchJSON<SessionMessagesResponse>(`/api/sessions/${encodeURIComponent(id)}/messages`),
  getSessionLatestDescendant: (id: string) =>
    fetchJSON<SessionLatestDescendantResponse>(
      `/api/sessions/${encodeURIComponent(id)}/latest-descendant`,
    ),
  deleteSession: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  getLogs: (params: { file?: string; lines?: number; level?: string; component?: string }) => {
    const qs = new URLSearchParams();
    if (params.file) qs.set("file", params.file);
    if (params.lines) qs.set("lines", String(params.lines));
    if (params.level && params.level !== "ALL") qs.set("level", params.level);
    if (params.component && params.component !== "all") qs.set("component", params.component);
    return fetchJSON<LogsResponse>(`/api/logs?${qs.toString()}`);
  },
  getAnalytics: (days: number) =>
    fetchJSON<AnalyticsResponse>(`/api/analytics/usage?days=${days}`),
  getModelsAnalytics: (days: number) =>
    fetchJSON<ModelsAnalyticsResponse>(`/api/analytics/models?days=${days}`),
  getConfig: () => fetchJSON<Record<string, unknown>>("/api/config"),
  getDefaults: () => fetchJSON<Record<string, unknown>>("/api/config/defaults"),
  getSchema: () => fetchJSON<{ fields: Record<string, unknown>; category_order: string[] }>("/api/config/schema"),
  getModelInfo: () => fetchJSON<ModelInfoResponse>("/api/model/info"),
  getModelOptions: () => fetchJSON<ModelOptionsResponse>("/api/model/options"),
  getAuxiliaryModels: () => fetchJSON<AuxiliaryModelsResponse>("/api/model/auxiliary"),
  setModelAssignment: (body: ModelAssignmentRequest) =>
    fetchJSON<ModelAssignmentResponse>("/api/model/set", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  saveConfig: (config: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    }),
  getConfigRaw: () => fetchJSON<{ yaml: string }>("/api/config/raw"),
  saveConfigRaw: (yaml_text: string) =>
    fetchJSON<{ ok: boolean }>("/api/config/raw", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml_text }),
    }),
  getEnvVars: () => fetchJSON<Record<string, EnvVarInfo>>("/api/env"),
  setEnvVar: (key: string, value: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    }),
  deleteEnvVar: (key: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    }),
  revealEnvVar: async (key: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ key: string; value: string }>("/api/env/reveal", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [SESSION_HEADER]: token,
      },
      body: JSON.stringify({ key }),
    });
  },

  // Cron jobs
  getCronJobs: () => fetchJSON<CronJob[]>("/api/cron/jobs"),
  createCronJob: (job: {
    prompt: string;
    schedule: string;
    name?: string;
    deliver?: string;
    authorization?: { required: boolean; roles?: string[]; users?: string[] };
  }) =>
    fetchJSON<CronJob>("/api/cron/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
    }),
  pauseCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/pause`, { method: "POST" }),
  resumeCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/resume`, { method: "POST" }),
  triggerCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/trigger`, { method: "POST" }),
  authorizeCronJob: (id: string, body: { approve: boolean; note?: string }) =>
    fetchJSON<CronJob>(`/api/cron/jobs/${id}/authorize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}`, { method: "DELETE" }),

  // Governed knowledge
  getKnowledgeLayers: () => fetchJSON<KnowledgeLayersResponse>("/api/knowledge/layers"),
  getKnowledgeApprovals: (status = "pending") =>
    fetchJSON<KnowledgeApprovalsResponse>(`/api/knowledge/approvals?status=${status}`),
  decideKnowledgeApproval: (id: string, body: { approve: boolean; note?: string }) =>
    fetchJSON<KnowledgeApprovalDecisionResponse>(
      `/api/knowledge/approvals/${encodeURIComponent(id)}/decide`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),

  // Staged file-change approvals
  getFileChangeApprovals: (status = "pending") =>
    fetchJSON<FileChangeApprovalsResponse>(`/api/files/approvals?status=${status}`),
  decideFileChangeApproval: (id: string, body: { approve: boolean; note?: string }) =>
    fetchJSON<FileChangeApprovalDecisionResponse>(
      `/api/files/approvals/${encodeURIComponent(id)}/decide`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),

  // Profiles (minimal)
  getProfiles: () =>
    fetchJSON<{ profiles: ProfileInfo[] }>("/api/profiles"),
  createProfile: (body: { name: string; clone_from_default: boolean }) =>
    fetchJSON<{ ok: boolean; name: string; path: string }>("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  renameProfile: (name: string, newName: string) =>
    fetchJSON<{ ok: boolean; name: string; path: string }>(
      `/api/profiles/${encodeURIComponent(name)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_name: newName }),
      },
    ),
  deleteProfile: (name: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/profiles/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
  getProfileSetupCommand: (name: string) =>
    fetchJSON<{ command: string }>(
      `/api/profiles/${encodeURIComponent(name)}/setup-command`,
    ),
  getProfileSoul: (name: string) =>
    fetchJSON<{ content: string; exists: boolean }>(
      `/api/profiles/${encodeURIComponent(name)}/soul`,
    ),
  updateProfileSoul: (name: string, content: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/profiles/${encodeURIComponent(name)}/soul`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    ),

  // Skills & Toolsets
  getSkills: () => fetchJSON<SkillInfo[]>("/api/skills"),
  toggleSkill: (name: string, enabled: boolean) =>
    fetchJSON<{ ok: boolean }>("/api/skills/toggle", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, enabled }),
    }),
  getToolsets: () => fetchJSON<ToolsetInfo[]>("/api/tools/toolsets"),

  // Session search (FTS5)
  searchSessions: (q: string) =>
    fetchJSON<SessionSearchResponse>(`/api/sessions/search?q=${encodeURIComponent(q)}`),

  // OAuth provider management
  getOAuthProviders: () =>
    fetchJSON<OAuthProvidersResponse>("/api/providers/oauth"),
  disconnectOAuthProvider: async (providerId: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ ok: boolean; provider: string }>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}`,
      {
        method: "DELETE",
        headers: { [SESSION_HEADER]: token },
      },
    );
  },
  startOAuthLogin: async (providerId: string) => {
    const token = await getSessionToken();
    return fetchJSON<OAuthStartResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/start`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [SESSION_HEADER]: token,
        },
        body: "{}",
      },
    );
  },
  submitOAuthCode: async (providerId: string, sessionId: string, code: string) => {
    const token = await getSessionToken();
    return fetchJSON<OAuthSubmitResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/submit`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [SESSION_HEADER]: token,
        },
        body: JSON.stringify({ session_id: sessionId, code }),
      },
    );
  },
  pollOAuthSession: (providerId: string, sessionId: string) =>
    fetchJSON<OAuthPollResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/poll/${encodeURIComponent(sessionId)}`,
    ),
  cancelOAuthSession: async (sessionId: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ ok: boolean }>(
      `/api/providers/oauth/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "DELETE",
        headers: { [SESSION_HEADER]: token },
      },
    );
  },

  // Gateway / update actions
  startGateway: () =>
    fetchJSON<ActionResponse>("/api/gateway/start", { method: "POST" }),
  restartGateway: () =>
    fetchJSON<ActionResponse>("/api/gateway/restart", { method: "POST" }),
  updateHermes: () =>
    fetchJSON<ActionResponse>("/api/hermes/update", { method: "POST" }),
  getActionStatus: (name: string, lines = 200) =>
    fetchJSON<ActionStatusResponse>(
      `/api/actions/${encodeURIComponent(name)}/status?lines=${lines}`,
    ),

  // Dashboard plugins
  getPlugins: () =>
    fetchJSON<PluginManifestResponse[]>("/api/dashboard/plugins"),
  rescanPlugins: () =>
    fetchJSON<{ ok: boolean; count: number }>("/api/dashboard/plugins/rescan"),

  getPluginsHub: () => fetchJSON<PluginsHubResponse>("/api/dashboard/plugins/hub"),

  installAgentPlugin: (body: AgentPluginInstallRequest) =>
    fetchJSON<AgentPluginInstallResponse>("/api/dashboard/agent-plugins/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body }),
    }),

  enableAgentPlugin: (name: string) =>
    fetchJSON<{ ok: boolean; name: string; unchanged?: boolean }>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}/enable`,
      { method: "POST" },
    ),

  disableAgentPlugin: (name: string) =>
    fetchJSON<{ ok: boolean; name: string; unchanged?: boolean }>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}/disable`,
      { method: "POST" },
    ),

  updateAgentPlugin: (name: string) =>
    fetchJSON<AgentPluginUpdateResponse>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}/update`,
      { method: "POST" },
    ),

  removeAgentPlugin: (name: string) =>
    fetchJSON<{ ok: boolean; name: string }>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),

  savePluginProviders: (body: PluginProvidersPutRequest) =>
    fetchJSON<{ ok: boolean }>("/api/dashboard/plugin-providers", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  setPluginVisibility: (name: string, hidden: boolean) =>
    fetchJSON<{ ok: boolean; name: string; hidden: boolean }>(
      `/api/dashboard/plugins/${encodeURIComponent(name)}/visibility`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hidden }),
      },
    ),

  // Dashboard themes
  getThemes: () =>
    fetchJSON<DashboardThemesResponse>("/api/dashboard/themes"),
  setTheme: (name: string) =>
    fetchJSON<{ ok: boolean; theme: string }>("/api/dashboard/theme", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
};

export interface ActionResponse {
  name: string;
  ok: boolean;
  pid: number;
}

export interface ActionStatusResponse {
  exit_code: number | null;
  lines: string[];
  name: string;
  pid: number | null;
  running: boolean;
}

export interface PlatformStatus {
  error_code?: string;
  error_message?: string;
  state: string;
  updated_at: string;
}

export interface GovernanceWarning {
  severity: "warning" | "error";
  code: string;
  message: string;
}

export interface OnboardingProviderEntry {
  slug: string;
  label: string;
  description: string;
  env_key: string | null;
  auth_type: string;
}

export interface OnboardingState {
  provider_configured: boolean;
  current_provider: string;
  current_model: string;
  current_effort: string;
  valid_efforts: string[];
  gateway_configured: boolean;
  governance_configured: boolean;
  dashboard_auth_configured: boolean;
  providers_catalog: OnboardingProviderEntry[];
}

export interface StatusResponse {
  active_sessions: number;
  config_path: string;
  config_version: number;
  env_path: string;
  gateway_exit_reason: string | null;
  gateway_health_url: string | null;
  gateway_pid: number | null;
  gateway_platforms: Record<string, PlatformStatus>;
  gateway_running: boolean;
  gateway_state: string | null;
  gateway_updated_at: string | null;
  hermes_home: string;
  latest_config_version: number;
  release_date: string;
  version: string;
  governance_warnings?: GovernanceWarning[];
}

export interface SessionInfo {
  id: string;
  source: string | null;
  model: string | null;
  title: string | null;
  started_at: number;
  ended_at: number | null;
  last_active: number;
  is_active: boolean;
  message_count: number;
  tool_call_count: number;
  input_tokens: number;
  output_tokens: number;
  preview: string | null;
  parent_session_id?: string | null;
}

export interface SessionLatestDescendantResponse {
  requested_session_id: string;
  session_id: string;
  path: string[];
  changed: boolean;
}

export interface PaginatedSessions {
  sessions: SessionInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface EnvVarInfo {
  is_set: boolean;
  redacted_value: string | null;
  description: string;
  url: string | null;
  category: string;
  is_password: boolean;
  tools: string[];
  advanced: boolean;
}

export interface SessionMessage {
  role: "user" | "assistant" | "system" | "tool";
  content: string | null;
  tool_calls?: Array<{
    id: string;
    function: { name: string; arguments: string };
  }>;
  tool_name?: string;
  tool_call_id?: string;
  timestamp?: number;
}

export interface SessionMessagesResponse {
  session_id: string;
  messages: SessionMessage[];
}

export interface LogsResponse {
  file: string;
  lines: string[];
}

export interface AnalyticsDailyEntry {
  day: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
  actual_cost: number;
  sessions: number;
  api_calls: number;
}

export interface AnalyticsModelEntry {
  model: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  sessions: number;
  api_calls: number;
}

export interface AnalyticsSkillEntry {
  skill: string;
  view_count: number;
  manage_count: number;
  total_count: number;
  percentage: number;
  last_used_at: number | null;
}

export interface AnalyticsSkillsSummary {
  total_skill_loads: number;
  total_skill_edits: number;
  total_skill_actions: number;
  distinct_skills_used: number;
}

export interface AnalyticsResponse {
  daily: AnalyticsDailyEntry[];
  by_model: AnalyticsModelEntry[];
  totals: {
    total_input: number;
    total_output: number;
    total_cache_read: number;
    total_reasoning: number;
    total_estimated_cost: number;
    total_actual_cost: number;
    total_sessions: number;
    total_api_calls: number;
  };
  skills: {
    summary: AnalyticsSkillsSummary;
    top_skills: AnalyticsSkillEntry[];
  };
}

export interface ProfileInfo {
  name: string;
  path: string;
  is_default: boolean;
  model: string | null;
  provider: string | null;
  has_env: boolean;
  skill_count: number;
}

export interface ModelsAnalyticsModelEntry {
  model: string;
  provider: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
  actual_cost: number;
  sessions: number;
  api_calls: number;
  tool_calls: number;
  last_used_at: number;
  avg_tokens_per_session: number;
  capabilities: {
    supports_tools?: boolean;
    supports_vision?: boolean;
    supports_reasoning?: boolean;
    context_window?: number;
    max_output_tokens?: number;
    model_family?: string;
  };
}

export interface ModelsAnalyticsResponse {
  models: ModelsAnalyticsModelEntry[];
  totals: {
    distinct_models: number;
    total_input: number;
    total_output: number;
    total_cache_read: number;
    total_reasoning: number;
    total_estimated_cost: number;
    total_actual_cost: number;
    total_sessions: number;
    total_api_calls: number;
  };
  period_days: number;
}

export interface CronJob {
  id: string;
  name?: string;
  prompt: string;
  schedule: { kind: string; expr: string; display: string };
  schedule_display: string;
  enabled: boolean;
  state: string;
  deliver?: string;
  paused_reason?: string | null;
  authorization?: {
    required?: boolean;
    roles?: string[];
    users?: string[];
    status?: string;
    requested_at?: string | null;
    approved_at?: string | null;
    approved_by?: string | null;
    denied_at?: string | null;
    denied_by?: string | null;
    note?: string | null;
  } | null;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_error?: string | null;
}

export interface KnowledgeCorporateLayer {
  memory_path: string;
  skills_dir: string;
  memory_exists: boolean;
  skill_count: number;
}

export interface KnowledgeTeamLayer extends KnowledgeCorporateLayer {
  name: string;
}

export interface KnowledgeLayersResponse {
  enabled: boolean;
  corporate: KnowledgeCorporateLayer;
  teams: KnowledgeTeamLayer[];
  user: {
    memory_dir: string;
    skills_dir: string;
  };
  pending_approvals: number;
}

export interface KnowledgeApproval {
  id: string;
  status: "pending" | "approved" | "denied";
  created_at: string;
  requested_by?: {
    id?: string;
    platform?: string | null;
    user_id?: string | null;
    user_name?: string | null;
  };
  scope: "corporate" | "team";
  team?: string | null;
  kind: "memory" | "skill";
  action: string;
  target?: string;
  name?: string | null;
  category?: string | null;
  file_path?: string | null;
  note?: string | null;
  content?: string | null;
  old_text?: string | null;
  decided_at?: string | null;
  decision_note?: string | null;
}

export interface KnowledgeApprovalsResponse {
  approvals: KnowledgeApproval[];
}

export interface KnowledgeApprovalDecisionResponse {
  success: boolean;
  approval: KnowledgeApproval;
}

export interface FileChangeApproval {
  id: string;
  status: "pending" | "approved" | "denied" | "stale";
  created_at: string;
  requested_by?: {
    id?: string;
    platform?: string | null;
    user_id?: string | null;
    user_name?: string | null;
  };
  origin?: {
    platform?: string;
    chat_id?: string;
    chat_name?: string;
    thread_id?: string;
    session_key?: string;
  };
  path: string;
  display_path?: string;
  operation: string;
  content?: string | null;
  base_exists?: boolean;
  diff?: string;
  requirement?: {
    roles?: string[];
    users?: string[];
    policy_path?: string | null;
  };
  note?: string | null;
  decided_at?: string | null;
  decided_by?: {
    id?: string;
  } | null;
  decision_note?: string | null;
}

export interface FileChangeApprovalsResponse {
  approvals: FileChangeApproval[];
}

export interface FileChangeApprovalDecisionResponse {
  success: boolean;
  approval: FileChangeApproval;
}

export interface SkillInfo {
  name: string;
  description: string;
  category: string;
  enabled: boolean;
  scope?: "corporate" | "team" | "user";
}

export interface ToolsetInfo {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  tools: string[];
}

export interface SessionSearchResult {
  session_id: string;
  snippet: string;
  role: string | null;
  source: string | null;
  model: string | null;
  session_started: number | null;
}

export interface SessionSearchResponse {
  results: SessionSearchResult[];
}

// ── Model info types ──────────────────────────────────────────────────

export interface ModelInfoResponse {
  model: string;
  provider: string;
  auto_context_length: number;
  config_context_length: number;
  effective_context_length: number;
  capabilities: {
    supports_tools?: boolean;
    supports_vision?: boolean;
    supports_reasoning?: boolean;
    context_window?: number;
    max_output_tokens?: number;
    model_family?: string;
  };
}

// ── Model options / assignment types ──────────────────────────────────

export interface ModelOptionProvider {
  name: string;
  slug: string;
  models?: string[];
  total_models?: number;
  is_current?: boolean;
  is_user_defined?: boolean;
  source?: string;
  warning?: string;
}

export interface ModelOptionsResponse {
  model?: string;
  provider?: string;
  providers?: ModelOptionProvider[];
}

export interface AuxiliaryTaskAssignment {
  task: string;
  provider: string;
  model: string;
  base_url: string;
}

export interface AuxiliaryModelsResponse {
  tasks: AuxiliaryTaskAssignment[];
  main: { provider: string; model: string };
}

export interface ModelAssignmentRequest {
  scope: "main" | "auxiliary";
  provider: string;
  model: string;
  /** For auxiliary: task slot name, "" for all, "__reset__" to reset all. */
  task?: string;
}

export interface ModelAssignmentResponse {
  ok: boolean;
  scope?: string;
  provider?: string;
  model?: string;
  tasks?: string[];
  reset?: boolean;
}

// ── OAuth provider types ────────────────────────────────────────────────

export interface OAuthProviderStatus {
  logged_in: boolean;
  source?: string | null;
  source_label?: string | null;
  token_preview?: string | null;
  expires_at?: string | null;
  has_refresh_token?: boolean;
  last_refresh?: string | null;
  error?: string;
}

export interface OAuthProvider {
  id: string;
  name: string;
  /** "pkce" (browser redirect + paste code), "device_code" (show code + URL),
   *  or "external" (delegated to a separate CLI like Claude Code or Qwen). */
  flow: "pkce" | "device_code" | "external";
  cli_command: string;
  docs_url: string;
  status: OAuthProviderStatus;
}

export interface OAuthProvidersResponse {
  providers: OAuthProvider[];
}

/** Discriminated union — the shape of /start depends on the flow. */
export type OAuthStartResponse =
  | {
      session_id: string;
      flow: "pkce";
      auth_url: string;
      expires_in: number;
    }
  | {
      session_id: string;
      flow: "device_code";
      user_code: string;
      verification_url: string;
      expires_in: number;
      poll_interval: number;
    };

export interface OAuthSubmitResponse {
  ok: boolean;
  status: "approved" | "error";
  message?: string;
}

export interface OAuthPollResponse {
  session_id: string;
  status: "pending" | "approved" | "denied" | "expired" | "error";
  error_message?: string | null;
  expires_at?: number | null;
}

// ── Dashboard theme types ──────────────────────────────────────────────

export interface DashboardThemeSummary {
  description: string;
  label: string;
  name: string;
  /** Full theme definition for user themes; undefined for built-ins
   *  (which the frontend already has locally). */
  definition?: DashboardTheme;
}

export interface DashboardThemesResponse {
  active: string;
  themes: DashboardThemeSummary[];
}

// ── Dashboard plugin types ─────────────────────────────────────────────

export interface PluginManifestResponse {
  name: string;
  label: string;
  description: string;
  icon: string;
  version: string;
  tab: {
    path: string;
    position?: string;
    override?: string;
    hidden?: boolean;
  };
  slots?: string[];
  entry: string;
  css?: string | null;
  has_api: boolean;
  source: string;
}

export interface HubAgentPluginRow {
  name: string;
  version: string;
  description: string;
  source: string;
  runtime_status: "disabled" | "enabled" | "inactive";
  has_dashboard_manifest: boolean;
  dashboard_manifest: PluginManifestResponse | null;
  path: string;
  can_remove: boolean;
  can_update_git: boolean;
  auth_required: boolean;
  auth_command: string;
  user_hidden: boolean;
}

export interface PluginsHubProviders {
  memory_provider: string;
  memory_options: Array<{ name: string; description: string }>;
  context_engine: string;
  context_options: Array<{ name: string; description: string }>;
}

export interface PluginsHubResponse {
  plugins: HubAgentPluginRow[];
  orphan_dashboard_plugins: PluginManifestResponse[];
  providers: PluginsHubProviders;
}

export interface AgentPluginInstallRequest {
  identifier: string;
  force?: boolean;
  enable?: boolean;
}

export interface AgentPluginInstallResponse {
  ok: boolean;
  plugin_name?: string;
  warnings?: string[];
  missing_env?: string[];
  after_install_path?: string | null;
  enabled?: boolean;
  error?: string;
}

export interface AgentPluginUpdateResponse {
  ok: boolean;
  name?: string;
  output?: string;
  unchanged?: boolean;
  error?: string;
}

export interface PluginProvidersPutRequest {
  memory_provider?: string;
  context_engine?: string;
}
