import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  ExternalLink,
  MessageSquare,
  Play,
  Plus,
  RefreshCw,
  RotateCw,
  Save,
  ShieldCheck,
  Terminal,
  Trash2,
  Users,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/NouiTypography";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import {
  api,
  type DiscordGatewayAccessUser,
  type DiscordGatewayAccessUsersResponse,
  type EnvVarInfo,
  type StatusResponse,
} from "@/lib/api";
import { PluginSlot } from "@/plugins";

type GatewayField = {
  key: string;
  label: string;
  placeholder?: string;
  secret?: boolean;
  required?: boolean;
  help?: string[];
};

type GatewayPlatform = {
  id: string;
  name: string;
  badge: string;
  description: string;
  docUrl: string;
  required: string[];
  requiredAny?: string[][];
  fields: GatewayField[];
  steps: string[];
  test: string;
};

type DiscordAccessUserDraft = {
  user_id: string;
  name: string;
  roles: string;
  teams: string;
};

function textToList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function newDiscordAccessRow(role = "operator"): DiscordAccessUserDraft {
  return { user_id: "", name: "", roles: role, teams: "" };
}

function discordUserToDraft(user: DiscordGatewayAccessUser): DiscordAccessUserDraft {
  return {
    user_id: user.user_id ?? "",
    name: user.name ?? "",
    roles: (user.roles ?? []).join(", ") || "operator",
    teams: (user.teams ?? []).join(", "),
  };
}

function normalizeDiscordRows(rows: DiscordAccessUserDraft[]): DiscordGatewayAccessUser[] {
  const seen = new Set<string>();
  return rows
    .map((row) => ({
      user_id: row.user_id.trim(),
      name: row.name.trim(),
      roles: textToList(row.roles),
      teams: textToList(row.teams),
    }))
    .filter((row) => row.user_id.length > 0)
    .filter((row) => {
      if (seen.has(row.user_id)) return false;
      seen.add(row.user_id);
      return true;
    });
}

// Platforms whose allowlist + governance roles are managed by the users
// editor instead of a raw comma-separated env field.
const ACCESS_PLATFORM_IDS = ["discord", "slack", "mattermost", "matrix"] as const;

const ACCESS_ENV_KEYS: Record<string, string> = {
  discord: "DISCORD_ALLOWED_USERS",
  slack: "SLACK_ALLOWED_USERS",
  mattermost: "MATTERMOST_ALLOWED_USERS",
  matrix: "MATRIX_ALLOWED_USERS",
};

const USER_ID_PLACEHOLDERS: Record<string, string> = {
  discord: "284102345871466496",
  slack: "U01ABC2DEF3",
  mattermost: "26characteruserid00000000a",
  matrix: "@ana:company.example",
};

const USER_ID_HELP: Record<string, string[]> = {
  discord: [
    "Enable Developer Mode: Discord Settings → Advanced → Developer Mode.",
    "Right-click the member (or open their profile → ⋯) and pick Copy User ID.",
    "It is a long number, e.g. 284102345871466496 — not the @username.",
  ],
  slack: [
    "Open the person's profile in Slack, click the ⋮ (three dots) menu, and pick Copy member ID.",
    "It starts with U or W, e.g. U01ABC2DEF3 — not the @display name.",
    "Your own ID: click your avatar → Profile → ⋮ → Copy member ID.",
  ],
  mattermost: [
    "Admins: System Console → User Management → Users, open the user — the ID is on their page.",
    "Or click a name in any channel to open the profile popover and copy the ID from it.",
    "It is a 26-character string of letters and numbers.",
  ],
  matrix: [
    "Use the full Matrix ID shown on the user's profile: @username:homeserver.",
    "Example: @ana:company.example — include the @ and the homeserver part.",
    "In Element: click the avatar → the ID is under the display name.",
  ],
};

const PLATFORMS: GatewayPlatform[] = [
  {
    id: "slack",
    name: "Slack",
    badge: "Recommended for companies",
    description:
      "Socket Mode gateway for corporate Slack workspaces. No public webhook URL is required.",
    docUrl: "https://ampliia.com/en/maia/docs/#gateway-setup",
    required: ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_ALLOWED_USERS"],
    fields: [
      { key: "SLACK_BOT_TOKEN", label: "Bot token", placeholder: "xoxb-...", secret: true, required: true },
      { key: "SLACK_APP_TOKEN", label: "App-level token", placeholder: "xapp-...", secret: true, required: true },
      { key: "SLACK_ALLOWED_USERS", label: "Allowed member IDs", placeholder: "U01ABC2DEF3,U09TEAMLEAD", required: true },
      { key: "SLACK_HOME_CHANNEL", label: "Home channel", placeholder: "C01234567890" },
    ],
    steps: [
      "Create a Slack app from the generated manifest or from scratch.",
      "Enable Socket Mode and create an xapp token with connections:write.",
      "Add message.im, message.channels, message.groups, and app_mention events.",
      "Install the app, copy the xoxb bot token, then invite the bot to channels.",
    ],
    test: "DM the bot, then test one approved channel with @Maia.",
  },
  {
    id: "discord",
    name: "Discord",
    badge: "Recommended for teams",
    description:
      "Discord bot gateway with direct messages, server channels, roles, slash commands, and threads.",
    docUrl: "https://ampliia.com/en/maia/docs/#gateway-setup",
    required: ["DISCORD_BOT_TOKEN"],
    requiredAny: [["DISCORD_ALLOWED_USERS", "DISCORD_ALLOWED_ROLES"]],
    fields: [
      {
        key: "DISCORD_BOT_TOKEN",
        label: "Bot token",
        placeholder: "Discord bot token",
        secret: true,
        required: true,
        help: [
          "Open Discord Developer Portal → Applications → your app → Bot.",
          "Click Reset Token / Copy Token and paste it here. Store it only as a secret; never commit it.",
          "Also enable Message Content Intent so the bot can read messages.",
        ],
      },
      {
        key: "DISCORD_ALLOWED_ROLES",
        label: "Allowed Discord role IDs",
        placeholder: "123456789012345678,987654321098765432",
        help: [
          "Optional alternative or complement to named users. Separate multiple role IDs with commas.",
          "In Discord, enable Developer Mode, right-click a role in Server Settings → Roles, then Copy Role ID.",
          "This grants gateway access to anyone holding that Discord role; Maia governance roles are still configured per user when needed.",
        ],
      },
      {
        key: "DISCORD_HOME_CHANNEL",
        label: "Home channel ID",
        placeholder: "234567890123456789",
        help: [
          "Optional channel for cron output, notifications, and proactive messages.",
          "Enable Developer Mode, right-click the target channel, then Copy Channel ID.",
        ],
      },
    ],
    steps: [
      "Create an application in the Discord Developer Portal.",
      "Enable Message Content Intent, and Server Members Intent if using roles.",
      "Invite the bot with bot and applications.commands scopes.",
      "Add the initial admin in the Discord users section below, or authorize a Discord role.",
    ],
    test: "DM the bot or mention it in an approved channel after the gateway starts.",
  },
  {
    id: "mattermost",
    name: "Mattermost",
    badge: "Self-hosted corporate chat",
    description:
      "Mattermost bot account gateway for companies that run their own chat server.",
    docUrl: "https://ampliia.com/en/maia/docs/#gateway-setup",
    required: ["MATTERMOST_URL", "MATTERMOST_TOKEN", "MATTERMOST_ALLOWED_USERS"],
    fields: [
      { key: "MATTERMOST_URL", label: "Server URL", placeholder: "https://mattermost.company.example", required: true },
      { key: "MATTERMOST_TOKEN", label: "Bot token", placeholder: "Mattermost bot token", secret: true, required: true },
      { key: "MATTERMOST_ALLOWED_USERS", label: "Allowed user IDs", placeholder: "26characteruserid", required: true },
      { key: "MATTERMOST_HOME_CHANNEL", label: "Home channel", placeholder: "channelid" },
      { key: "MATTERMOST_REPLY_MODE", label: "Reply mode", placeholder: "off" },
    ],
    steps: [
      "Enable bot accounts in Mattermost if needed.",
      "Create a bot account and copy the bot token.",
      "Copy real Mattermost user IDs, not usernames.",
      "Limit the bot to approved teams and channels.",
    ],
    test: "Message the bot from an allowed Mattermost user and verify it replies.",
  },
  {
    id: "matrix",
    name: "Matrix",
    badge: "Self-hosted or federated",
    description:
      "Matrix bot user gateway for self-hosted or federated corporate chat.",
    docUrl: "https://ampliia.com/en/maia/docs/#gateway-setup",
    required: ["MATRIX_HOMESERVER", "MATRIX_USER_ID", "MATRIX_ALLOWED_USERS"],
    requiredAny: [["MATRIX_ACCESS_TOKEN", "MATRIX_PASSWORD"]],
    fields: [
      { key: "MATRIX_HOMESERVER", label: "Homeserver URL", placeholder: "https://matrix.company.example", required: true },
      { key: "MATRIX_USER_ID", label: "Bot user ID", placeholder: "@maia:company.example", required: true },
      { key: "MATRIX_ACCESS_TOKEN", label: "Access token", placeholder: "Matrix access token", secret: true },
      { key: "MATRIX_PASSWORD", label: "Password login", placeholder: "Only if not using access token", secret: true },
      { key: "MATRIX_ALLOWED_USERS", label: "Allowed user IDs", placeholder: "@ana:company.example,@bruno:company.example", required: true },
      { key: "MATRIX_HOME_ROOM", label: "Home room", placeholder: "!roomid:company.example" },
      { key: "MATRIX_ENCRYPTION", label: "E2EE", placeholder: "false" },
    ],
    steps: [
      "Create a dedicated Matrix bot user on the homeserver.",
      "Use an access token when possible; otherwise use password login.",
      "Use full Matrix user IDs in the allowlist.",
      "Test encryption dependencies separately before enabling E2EE for users.",
    ],
    test: "Invite the bot user to a room, then send a message from an allowed Matrix user.",
  },
];

function envIsSet(env: Record<string, EnvVarInfo>, key: string): boolean {
  return Boolean(env[key]?.is_set);
}

function fieldStatus(env: Record<string, EnvVarInfo>, key: string): string {
  const info = env[key];
  if (!info) return "not tracked";
  if (!info.is_set) return "not set";
  return info.redacted_value || "set";
}

function platformConfigured(platform: GatewayPlatform, env: Record<string, EnvVarInfo>): boolean {
  const requiredOk = platform.required.every((key) => envIsSet(env, key));
  const anyOk =
    platform.requiredAny?.every((group) => group.some((key) => envIsSet(env, key))) ?? true;
  return requiredOk && anyOk;
}

function missingRequirements(
  platform: GatewayPlatform,
  env: Record<string, EnvVarInfo>,
  draft: Record<string, string>,
  extraDraftKeys: Set<string> = new Set(),
): string[] {
  const missing = platform.required.filter(
    (key) => !envIsSet(env, key) && !draft[key]?.trim() && !extraDraftKeys.has(key),
  );
  for (const group of platform.requiredAny ?? []) {
    const hasExisting = group.some((key) => envIsSet(env, key));
    const hasDraft = group.some((key) => draft[key]?.trim() || extraDraftKeys.has(key));
    if (!hasExisting && !hasDraft) {
      missing.push(group.join(" or "));
    }
  }
  return missing;
}

function gatewayRuntimeLabel(status: StatusResponse | null): string {
  if (!status) return "unknown";
  if (status.gateway_running) return status.gateway_state || "running";
  return status.gateway_state || "stopped";
}

export default function GatewayPage() {
  const [env, setEnv] = useState<Record<string, EnvVarInfo>>({});
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const [accessRows, setAccessRows] = useState<Record<string, DiscordAccessUserDraft[]>>(
    () =>
      Object.fromEntries(
        ACCESS_PLATFORM_IDS.map((id) => [id, [newDiscordAccessRow("admin")]]),
      ),
  );
  const [roleOptions, setRoleOptions] = useState<string[]>([]);
  const [teamOptions, setTeamOptions] = useState<string[]>([]);
  const [helpOpen, setHelpOpen] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const { toast, showToast } = useToast();

  const configuredCount = useMemo(
    () => PLATFORMS.filter((platform) => platformConfigured(platform, env)).length,
    [env],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextEnv, nextStatus, ...accessLists] = await Promise.all([
        api.getEnvVars(),
        api.getStatus(),
        ...ACCESS_PLATFORM_IDS.map((id) =>
          api
            .getGatewayAccessUsers(id)
            .catch((): DiscordGatewayAccessUsersResponse => ({ users: [] })),
        ),
      ]);
      setEnv(nextEnv);
      setStatus(nextStatus);
      const nextRows: Record<string, DiscordAccessUserDraft[]> = {};
      ACCESS_PLATFORM_IDS.forEach((id, index) => {
        const rows = (accessLists[index]?.users ?? []).map(discordUserToDraft);
        nextRows[id] = rows.length ? rows : [newDiscordAccessRow("admin")];
      });
      setAccessRows(nextRows);
      // Governance role/team options ride along on any access response.
      const withOptions = accessLists.find((list) => (list?.roles?.length ?? 0) > 0);
      setRoleOptions(withOptions?.roles ?? []);
      setTeamOptions(withOptions?.teams ?? []);
    } catch (err) {
      showToast(`Failed to load gateway settings: ${err}`, "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  const setDraftValue = (platformId: string, key: string, value: string) => {
    setDrafts((current) => ({
      ...current,
      [platformId]: {
        ...(current[platformId] ?? {}),
        [key]: value,
      },
    }));
  };

  const toggleFieldHelp = (key: string) => {
    setHelpOpen((current) => ({ ...current, [key]: !current[key] }));
  };

  const updateAccessRow = (
    platformId: string,
    index: number,
    patch: Partial<DiscordAccessUserDraft>,
  ) => {
    setAccessRows((current) => ({
      ...current,
      [platformId]: (current[platformId] ?? []).map((row, rowIndex) =>
        rowIndex === index ? { ...row, ...patch } : row,
      ),
    }));
  };

  const addAccessRow = (platformId: string, role = "operator") => {
    setAccessRows((current) => ({
      ...current,
      [platformId]: [...(current[platformId] ?? []), newDiscordAccessRow(role)],
    }));
  };

  const removeAccessRow = (platformId: string, index: number) => {
    setAccessRows((current) => {
      const next = (current[platformId] ?? []).filter((_, rowIndex) => rowIndex !== index);
      return {
        ...current,
        [platformId]: next.length ? next : [newDiscordAccessRow("admin")],
      };
    });
  };

  const setPlatformRows = (platformId: string, users: DiscordGatewayAccessUser[]) => {
    const rows = users.map(discordUserToDraft);
    setAccessRows((current) => ({
      ...current,
      [platformId]: rows.length ? rows : [newDiscordAccessRow("admin")],
    }));
  };

  const saveAccessUsers = async (platform: GatewayPlatform) => {
    const users = normalizeDiscordRows(accessRows[platform.id] ?? []);
    if (!users.length) {
      showToast(`Add at least one ${platform.name} user ID before saving.`, "error");
      return;
    }
    setBusy(`${platform.id}:access-users`);
    try {
      const response = await api.saveGatewayAccessUsers(platform.id, { users });
      setPlatformRows(platform.id, response.users);
      showToast(
        `${platform.name} users and governance roles saved. Restart the gateway to apply the allowlist.`,
        "success",
      );
      await load();
    } catch (err) {
      showToast(`Failed to save ${platform.name} users: ${err}`, "error");
    } finally {
      setBusy("");
    }
  };

  const savePlatform = async (platform: GatewayPlatform) => {
    const draft = drafts[platform.id] ?? {};
    const allowKey = ACCESS_ENV_KEYS[platform.id];
    const accessUsers = allowKey ? normalizeDiscordRows(accessRows[platform.id] ?? []) : [];
    const extraDraftKeys = new Set<string>();
    if (allowKey && accessUsers.length) extraDraftKeys.add(allowKey);
    const missing = missingRequirements(platform, env, draft, extraDraftKeys);
    if (missing.length) {
      showToast(`Missing required gateway values: ${missing.join(", ")}`, "error");
      return;
    }

    const entries = Object.entries(draft)
      .map(([key, value]) => [key, value.trim()] as const)
      .filter(([, value]) => value.length > 0)
      .filter(([key]) => !(allowKey && key === allowKey && accessUsers.length));

    if (!entries.length && !(allowKey && accessUsers.length)) {
      showToast("No new gateway values to save.", "success");
      return;
    }

    setBusy(`save:${platform.id}`);
    try {
      for (const [key, value] of entries) {
        await api.setEnvVar(key, value);
      }
      if (allowKey && accessUsers.length) {
        const response = await api.saveGatewayAccessUsers(platform.id, { users: accessUsers });
        setPlatformRows(platform.id, response.users);
      }
      setDrafts((current) => ({ ...current, [platform.id]: {} }));
      showToast(`${platform.name} gateway values saved. Restart the gateway to apply them.`, "success");
      await load();
    } catch (err) {
      showToast(`Failed to save ${platform.name}: ${err}`, "error");
    } finally {
      setBusy("");
    }
  };

  const startGateway = async () => {
    setBusy("gateway:start");
    try {
      await api.startGateway();
      showToast("Gateway start requested. Check logs if it does not come online.", "success");
      await load();
    } catch (err) {
      showToast(`Gateway start failed: ${err}`, "error");
    } finally {
      setBusy("");
    }
  };

  const restartGateway = async () => {
    setBusy("gateway:restart");
    try {
      await api.restartGateway();
      showToast("Gateway restart requested.", "success");
      await load();
    } catch (err) {
      showToast(`Gateway restart failed: ${err}`, "error");
    } finally {
      setBusy("");
    }
  };

  const copyCommand = async (command: string) => {
    try {
      await navigator.clipboard.writeText(command);
      showToast("Command copied.", "success");
    } catch {
      showToast(command, "success");
    }
  };

  if (loading && !Object.keys(env).length) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner className="text-2xl text-primary" />
      </div>
    );
  }

  const runtime = gatewayRuntimeLabel(status);
  const runtimeTone = status?.gateway_running ? "success" : "destructive";

  return (
    <div className="flex flex-col gap-6">
      <PluginSlot name="gateway:top" />
      <Toast toast={toast} />

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={runtimeTone}>{runtime}</Badge>
          <Badge tone="outline">{configuredCount}/{PLATFORMS.length} corporate platforms configured</Badge>
          <Badge tone="secondary">Slack and Discord first</Badge>
        </div>
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <H2 variant="sm" className="flex items-center gap-2 text-muted-foreground">
              <MessageSquare className="h-4 w-4" />
              Messaging Gateway
            </H2>
            <p className="mt-2 max-w-4xl text-sm normal-case leading-6 text-muted-foreground">
              Configure how employees talk to Maia from Slack, Discord,
              Mattermost, or Matrix. Save credentials here, then start or restart
              the gateway and test with an allowed user before inviting a wider team.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" outlined onClick={load} disabled={loading}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
            <Button size="sm" onClick={startGateway} disabled={Boolean(busy)}>
              <Play className="h-4 w-4" />
              Start
            </Button>
            <Button size="sm" outlined onClick={restartGateway} disabled={Boolean(busy)}>
              <RotateCw className="h-4 w-4" />
              Restart
            </Button>
          </div>
        </div>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4" />
            Required rollout flow
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm normal-case leading-6 text-muted-foreground md:grid-cols-4">
          {[
            "Choose Slack, Discord, Mattermost, or Matrix.",
            "Save required bot credentials and user or role allowlists.",
            "Start or restart the gateway service.",
            "Test /dashboard from a private chat and approve access in Dashboard Access.",
          ].map((item) => (
            <div key={item} className="flex items-start gap-2 border border-border/60 p-3">
              <CheckCircle2 className="mt-1 h-3.5 w-3.5 shrink-0 text-success" />
              <span>{item}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
        {PLATFORMS.map((platform) => {
          const configured = platformConfigured(platform, env);
          const draft = drafts[platform.id] ?? {};
          const saveBusy = busy === `save:${platform.id}`;
          return (
            <Card key={platform.id} className={configured ? "border-success/40" : ""}>
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <MessageSquare className="h-4 w-4" />
                      {platform.name}
                    </CardTitle>
                    <p className="mt-2 text-sm normal-case leading-6 text-muted-foreground">
                      {platform.description}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge tone={configured ? "success" : "warning"}>
                      {configured ? "configured" : "needs setup"}
                    </Badge>
                    <Badge tone="outline">{platform.badge}</Badge>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-5">
                <div className="grid gap-3 md:grid-cols-2">
                  {platform.fields
                    .filter((field) => field.key !== ACCESS_ENV_KEYS[platform.id])
                    .map((field) => {
                    const info = env[field.key];
                    const current = fieldStatus(env, field.key);
                    const helpKey = `${platform.id}:${field.key}`;
                    const fallbackHelp = [info?.description, info?.url ? `Reference: ${info.url}` : ""].filter(
                      (item): item is string => Boolean(item),
                    );
                    const helpItems = field.help?.length ? field.help : fallbackHelp;
                    return (
                      <label key={field.key} className="grid gap-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex min-w-0 items-center gap-1.5">
                            <Label className="font-mono-ui text-[0.7rem]">
                              {field.label}
                              {field.required ? " *" : ""}
                            </Label>
                            {helpItems.length ? (
                              <button
                                type="button"
                                className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-border text-[0.65rem] font-bold text-muted-foreground hover:border-primary hover:text-primary"
                                aria-label={`Show help for ${field.label}`}
                                aria-expanded={Boolean(helpOpen[helpKey])}
                                onClick={(event) => {
                                  event.preventDefault();
                                  toggleFieldHelp(helpKey);
                                }}
                              >
                                ?
                              </button>
                            ) : null}
                          </div>
                          <span className="max-w-40 truncate text-right font-mono-ui text-[0.65rem] text-muted-foreground">
                            {current}
                          </span>
                        </div>
                        <Input
                          type={field.secret || info?.is_password ? "password" : "text"}
                          value={draft[field.key] ?? ""}
                          placeholder={field.placeholder || field.key}
                          onChange={(event) =>
                            setDraftValue(platform.id, field.key, event.target.value)
                          }
                          autoComplete="off"
                        />
                        {helpItems.length && helpOpen[helpKey] ? (
                          <div className="rounded-sm border border-border/60 bg-muted/30 p-3 text-xs normal-case leading-5 text-muted-foreground">
                            <ul className="list-disc space-y-1 pl-4">
                              {helpItems.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                      </label>
                    );
                  })}
                </div>

                <div className="grid gap-3 lg:grid-cols-2">
                  <div className="border border-border/60 p-3">
                    <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
                      <Terminal className="h-3.5 w-3.5" />
                      Setup checklist
                    </div>
                    <div className="space-y-2">
                      {platform.steps.map((step) => (
                        <div key={step} className="flex items-start gap-2 text-xs normal-case leading-5 text-muted-foreground">
                          <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-success" />
                          <span>{step}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="border border-border/60 p-3">
                    <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      Test before rollout
                    </div>
                    <p className="text-xs normal-case leading-5 text-muted-foreground">
                      {platform.test}
                    </p>
                    <a
                      href={platform.docUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-3 inline-flex items-center gap-1 text-xs font-bold uppercase tracking-[0.08em] text-primary hover:underline"
                    >
                      Gateway docs <ExternalLink className="h-3 w-3" />
                    </a>
                  </div>
                </div>

                <GatewayAccessUsersEditor
                  platform={platform}
                  rows={accessRows[platform.id] ?? []}
                  roleOptions={roleOptions}
                  teamOptions={teamOptions}
                  busy={busy === `${platform.id}:access-users`}
                  disabled={Boolean(busy)}
                  configured={configured}
                  onAdd={(role) => addAccessRow(platform.id, role)}
                  onRemove={(index) => removeAccessRow(platform.id, index)}
                  onSave={() => saveAccessUsers(platform)}
                  onUpdate={(index, patch) => updateAccessRow(platform.id, index, patch)}
                />

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-4">
                  <Button
                    size="sm"
                    outlined
                    onClick={() => copyCommand("maia setup gateway")}
                  >
                    <Copy className="h-4 w-4" />
                    Copy CLI wizard
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => savePlatform(platform)}
                    disabled={saveBusy || Boolean(busy && !saveBusy)}
                  >
                    {saveBusy ? <Spinner className="h-4 w-4" /> : <Save className="h-4 w-4" />}
                    Save {platform.name}
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Terminal className="h-4 w-4" />
            Service commands
          </CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="overflow-auto rounded-sm border border-border bg-black/30 p-3 font-mono-ui text-xs normal-case text-foreground">
{`maia setup gateway
maia gateway run       # foreground test
maia gateway install   # background service
maia gateway start
maia gateway status
maia logs gateway`}
          </pre>
        </CardContent>
      </Card>

      <PluginSlot name="gateway:bottom" />
    </div>
  );
}


const DEFAULT_ROLE_OPTIONS = ["viewer", "operator", "manager", "admin"];

type GatewayAccessUsersEditorProps = {
  platform: GatewayPlatform;
  rows: DiscordAccessUserDraft[];
  roleOptions: string[];
  teamOptions: string[];
  busy: boolean;
  disabled: boolean;
  configured: boolean;
  onAdd: (role?: string) => void;
  onRemove: (index: number) => void;
  onSave: () => void;
  onUpdate: (index: number, patch: Partial<DiscordAccessUserDraft>) => void;
};

function GatewayAccessUsersEditor({
  platform,
  rows,
  roleOptions,
  teamOptions,
  busy,
  disabled,
  configured,
  onAdd,
  onRemove,
  onSave,
  onUpdate,
}: GatewayAccessUsersEditorProps) {
  const [idHelpOpen, setIdHelpOpen] = useState(false);
  const [teamsHelpOpen, setTeamsHelpOpen] = useState(false);
  const allowKey = ACCESS_ENV_KEYS[platform.id] ?? "";
  const idPlaceholder = USER_ID_PLACEHOLDERS[platform.id] ?? "user id";
  const idHelp = USER_ID_HELP[platform.id] ?? [];
  const roleChoices = roleOptions.length ? roleOptions : DEFAULT_ROLE_OPTIONS;
  const teamsListId = `gateway-team-options-${platform.id}`;

  return (
    <div className="rounded-sm border border-border/70 bg-muted/20 p-4">
      <div>
        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
          <Users className="h-3.5 w-3.5" />
          {platform.name} users and access levels
        </div>
        <p className="mt-2 max-w-3xl text-xs normal-case leading-5 text-muted-foreground">
          Add the first admin here, then add normal users as the rollout grows. Saving this list writes
          {" "}
          <code>{allowKey}</code> (who may talk to Maia on {platform.name}) and stores names, roles, and
          {" "}
          teams under <code>governance.users</code>. Gateway access lets a user talk to the bot; governance
          {" "}
          roles decide what they can do inside configured policies. Dashboard access still uses the protected
          {" "}
          dashboard token/request flow.
        </p>
        {!configured && (
          <p className="mt-2 text-xs normal-case leading-5 text-warning">
            Fill in and save the credentials above first — users added here
            only take effect once the bot can connect.
          </p>
        )}
      </div>

      {rows.length === 0 && (
        <p className="mt-4 text-xs normal-case leading-5 text-muted-foreground">
          No users yet. Start by adding yourself as the first admin.
        </p>
      )}

      <div className="mt-4 grid gap-3">
        {rows.map((row, index) => (
          <div key={`${index}:${row.user_id}`} className="grid gap-3 border border-border/60 p-3 xl:grid-cols-[1.2fr_1.2fr_1fr_1fr_auto]">
            <label className="grid gap-1.5">
              <div className="flex items-center gap-1.5">
                <Label className="font-mono-ui text-[0.7rem]">{platform.name} user ID</Label>
                {idHelp.length > 0 && index === 0 && (
                  <button
                    type="button"
                    className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-border text-[0.65rem] font-bold text-muted-foreground hover:border-primary hover:text-primary"
                    aria-label={`How to find a ${platform.name} user ID`}
                    aria-expanded={idHelpOpen}
                    onClick={(event) => {
                      event.preventDefault();
                      setIdHelpOpen((open) => !open);
                    }}
                  >
                    ?
                  </button>
                )}
              </div>
              <Input
                value={row.user_id}
                placeholder={idPlaceholder}
                onChange={(event) => onUpdate(index, { user_id: event.target.value })}
                autoComplete="off"
              />
              {idHelpOpen && index === 0 && idHelp.length > 0 && (
                <div className="rounded-sm border border-border/60 bg-muted/30 p-3 text-xs normal-case leading-5 text-muted-foreground">
                  <ul className="list-disc space-y-1 pl-4">
                    {idHelp.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </label>
            <label className="grid gap-1.5">
              <Label className="font-mono-ui text-[0.7rem]">Name / label</Label>
              <Input
                value={row.name}
                placeholder="Ana Admin"
                onChange={(event) => onUpdate(index, { name: event.target.value })}
                autoComplete="off"
              />
            </label>
            <label className="grid gap-1.5">
              <Label className="font-mono-ui text-[0.7rem]">Access level (role)</Label>
              <select
                value={row.roles}
                onChange={(event) => onUpdate(index, { roles: event.target.value })}
                className="h-9 w-full border border-border bg-background px-2 text-sm"
              >
                {row.roles && !roleChoices.includes(row.roles) && (
                  <option value={row.roles}>{row.roles}</option>
                )}
                {roleChoices.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5">
              <div className="flex items-center gap-1.5">
                <Label className="font-mono-ui text-[0.7rem]">Teams</Label>
                {index === 0 && (
                  <button
                    type="button"
                    className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-border text-[0.65rem] font-bold text-muted-foreground hover:border-primary hover:text-primary"
                    aria-label="What teams are and where they are managed"
                    aria-expanded={teamsHelpOpen}
                    onClick={(event) => {
                      event.preventDefault();
                      setTeamsHelpOpen((open) => !open);
                    }}
                  >
                    ?
                  </button>
                )}
              </div>
              <Input
                list={teamsListId}
                value={row.teams}
                placeholder="engineering, finance"
                onChange={(event) => onUpdate(index, { teams: event.target.value })}
                autoComplete="off"
              />
              {teamsHelpOpen && index === 0 && (
                <div className="rounded-sm border border-border/60 bg-muted/30 p-3 text-xs normal-case leading-5 text-muted-foreground">
                  <p>
                    Teams group users for shared knowledge and folder access. A
                    team exists as soon as something references it — just type a
                    name here (comma-separate several). What each team can reach
                    is managed in{" "}
                    <Link to="/file-access" className="font-bold text-primary hover:underline">
                      File Access
                    </Link>{" "}
                    (delegated team roots and folder policies) and team knowledge
                    in{" "}
                    <Link to="/knowledge" className="font-bold text-primary hover:underline">
                      Knowledge
                    </Link>
                    ; assignments live under <code>governance.users</code> in{" "}
                    <Link
                      to="/config?search=governance"
                      className="font-bold text-primary hover:underline"
                    >
                      Config
                    </Link>
                    .
                  </p>
                  {teamOptions.length > 0 && (
                    <p className="mt-1">Existing teams: {teamOptions.join(", ")}.</p>
                  )}
                </div>
              )}
            </label>
            <Button
              size="xs"
              outlined
              className="self-end"
              onClick={() => onRemove(index)}
              disabled={disabled}
              aria-label={`Remove ${platform.name} user`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ))}
      </div>

      <datalist id={teamsListId}>
        {teamOptions.map((team) => (
          <option key={team} value={team} />
        ))}
      </datalist>

      <div className="mt-3 grid gap-2 text-xs normal-case leading-5 text-muted-foreground md:grid-cols-3">
        <div><strong>Multiple users:</strong> add one row per user ID; the saved allowlist is comma-separated automatically.</div>
        <div><strong>Normal users:</strong> use <code>operator</code> or <code>viewer</code> unless they need management abilities.</div>
        <div><strong>Admins:</strong> keep <code>admin</code> limited to people who can manage config, secrets, and access.</div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-end gap-3 border-t border-border/60 pt-4">
        <Button
          size="sm"
          outlined
          onClick={() => onAdd(rows.length === 0 ? "admin" : "operator")}
          disabled={disabled}
        >
          <Plus className="h-4 w-4" />
          {rows.length === 0 ? "Add first admin" : "Add user"}
        </Button>
        <Button size="sm" onClick={onSave} disabled={disabled || rows.length === 0}>
          {busy ? <Spinner className="h-4 w-4" /> : <Save className="h-4 w-4" />}
          Save users
        </Button>
      </div>
    </div>
  );
}
