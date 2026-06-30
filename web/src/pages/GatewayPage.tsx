import { useCallback, useEffect, useMemo, useState } from "react";
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
import { api, type DiscordGatewayAccessUser, type EnvVarInfo, type StatusResponse } from "@/lib/api";
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

const PLATFORMS: GatewayPlatform[] = [
  {
    id: "slack",
    name: "Slack",
    badge: "Recommended for companies",
    description:
      "Socket Mode gateway for corporate Slack workspaces. No public webhook URL is required.",
    docUrl: "https://ampliia.com/en/coorporate-hermes/docs/#gateway-setup",
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
    test: "DM the bot, then test one approved channel with @Coorporate Hermes.",
  },
  {
    id: "discord",
    name: "Discord",
    badge: "Recommended for teams",
    description:
      "Discord bot gateway with direct messages, server channels, roles, slash commands, and threads.",
    docUrl: "https://ampliia.com/en/coorporate-hermes/docs/#gateway-setup",
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
          "This grants gateway access to anyone holding that Discord role; Coorporate Hermes governance roles are still configured per user when needed.",
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
    docUrl: "https://ampliia.com/en/coorporate-hermes/docs/#gateway-setup",
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
    docUrl: "https://ampliia.com/en/coorporate-hermes/docs/#gateway-setup",
    required: ["MATRIX_HOMESERVER", "MATRIX_USER_ID", "MATRIX_ALLOWED_USERS"],
    requiredAny: [["MATRIX_ACCESS_TOKEN", "MATRIX_PASSWORD"]],
    fields: [
      { key: "MATRIX_HOMESERVER", label: "Homeserver URL", placeholder: "https://matrix.company.example", required: true },
      { key: "MATRIX_USER_ID", label: "Bot user ID", placeholder: "@coorporate-hermes:company.example", required: true },
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
  const [discordAccessRows, setDiscordAccessRows] = useState<DiscordAccessUserDraft[]>([
    newDiscordAccessRow("admin"),
  ]);
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
      const [nextEnv, nextStatus, discordAccess] = await Promise.all([
        api.getEnvVars(),
        api.getStatus(),
        api.getDiscordGatewayAccessUsers().catch(() => ({ users: [] })),
      ]);
      setEnv(nextEnv);
      setStatus(nextStatus);
      const rows = discordAccess.users.map(discordUserToDraft);
      setDiscordAccessRows(rows.length ? rows : [newDiscordAccessRow("admin")]);
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

  const updateDiscordAccessRow = (index: number, patch: Partial<DiscordAccessUserDraft>) => {
    setDiscordAccessRows((current) =>
      current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)),
    );
  };

  const addDiscordAccessRow = (role = "operator") => {
    setDiscordAccessRows((current) => [...current, newDiscordAccessRow(role)]);
  };

  const removeDiscordAccessRow = (index: number) => {
    setDiscordAccessRows((current) => {
      const next = current.filter((_, rowIndex) => rowIndex !== index);
      return next.length ? next : [newDiscordAccessRow("admin")];
    });
  };

  const saveDiscordAccessUsers = async () => {
    const users = normalizeDiscordRows(discordAccessRows);
    if (!users.length) {
      showToast("Add at least one Discord user ID before saving.", "error");
      return;
    }
    setBusy("discord:access-users");
    try {
      const response = await api.saveDiscordGatewayAccessUsers({ users });
      const rows = response.users.map(discordUserToDraft);
      setDiscordAccessRows(rows.length ? rows : [newDiscordAccessRow("admin")]);
      showToast("Discord gateway users and governance roles saved. Restart the gateway to apply the allowlist.", "success");
      await load();
    } catch (err) {
      showToast(`Failed to save Discord users: ${err}`, "error");
    } finally {
      setBusy("");
    }
  };

  const savePlatform = async (platform: GatewayPlatform) => {
    const draft = drafts[platform.id] ?? {};
    const discordUsers = platform.id === "discord" ? normalizeDiscordRows(discordAccessRows) : [];
    const extraDraftKeys = new Set<string>();
    if (discordUsers.length) extraDraftKeys.add("DISCORD_ALLOWED_USERS");
    const missing = missingRequirements(platform, env, draft, extraDraftKeys);
    if (missing.length) {
      showToast(`Missing required gateway values: ${missing.join(", ")}`, "error");
      return;
    }

    const entries = Object.entries(draft)
      .map(([key, value]) => [key, value.trim()] as const)
      .filter(([, value]) => value.length > 0)
      .filter(([key]) => !(platform.id === "discord" && key === "DISCORD_ALLOWED_USERS" && discordUsers.length));

    if (!entries.length && !(platform.id === "discord" && discordUsers.length)) {
      showToast("No new gateway values to save.", "success");
      return;
    }

    setBusy(`save:${platform.id}`);
    try {
      for (const [key, value] of entries) {
        await api.setEnvVar(key, value);
      }
      if (platform.id === "discord" && discordUsers.length) {
        const response = await api.saveDiscordGatewayAccessUsers({ users: discordUsers });
        const rows = response.users.map(discordUserToDraft);
        setDiscordAccessRows(rows.length ? rows : [newDiscordAccessRow("admin")]);
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
              Configure how employees talk to Coorporate Hermes from Slack, Discord,
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
                {platform.id === "discord" && (
                  <DiscordAccessUsersEditor
                    rows={discordAccessRows}
                    busy={busy === "discord:access-users"}
                    disabled={Boolean(busy)}
                    onAdd={addDiscordAccessRow}
                    onRemove={removeDiscordAccessRow}
                    onSave={saveDiscordAccessUsers}
                    onUpdate={updateDiscordAccessRow}
                  />
                )}

                <div className="grid gap-3 md:grid-cols-2">
                  {platform.fields.map((field) => {
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

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-4">
                  <Button
                    size="sm"
                    outlined
                    onClick={() => copyCommand("coorporate setup gateway")}
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
{`coorporate setup gateway
coorporate gateway run       # foreground test
coorporate gateway install   # background service
coorporate gateway start
coorporate gateway status
coorporate logs gateway`}
          </pre>
        </CardContent>
      </Card>

      <PluginSlot name="gateway:bottom" />
    </div>
  );
}


type DiscordAccessUsersEditorProps = {
  rows: DiscordAccessUserDraft[];
  busy: boolean;
  disabled: boolean;
  onAdd: (role?: string) => void;
  onRemove: (index: number) => void;
  onSave: () => void;
  onUpdate: (index: number, patch: Partial<DiscordAccessUserDraft>) => void;
};

function DiscordAccessUsersEditor({
  rows,
  busy,
  disabled,
  onAdd,
  onRemove,
  onSave,
  onUpdate,
}: DiscordAccessUsersEditorProps) {
  return (
    <div className="rounded-sm border border-border/70 bg-muted/20 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
            <Users className="h-3.5 w-3.5" />
            Discord users and governance roles
          </div>
          <p className="mt-2 max-w-3xl text-xs normal-case leading-5 text-muted-foreground">
            Add the first admin here, then add normal users as the rollout grows. Saving this list writes
            {" "}
            <code>DISCORD_ALLOWED_USERS</code> for gateway access and stores names, roles, and teams under
            {" "}
            <code>governance.users</code>. Gateway access lets a user talk to the bot; governance roles decide
            {" "}
            what they can do inside configured policies. Dashboard access still uses the protected dashboard
            {" "}
            token/request flow.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="xs" outlined onClick={() => onAdd("operator")} disabled={disabled}>
            <Plus className="h-3.5 w-3.5" />
            Add user
          </Button>
          <Button size="xs" onClick={onSave} disabled={disabled}>
            {busy ? <Spinner className="h-3.5 w-3.5" /> : <Save className="h-3.5 w-3.5" />}
            Save users
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-3">
        {rows.map((row, index) => (
          <div key={`${index}:${row.user_id}`} className="grid gap-3 border border-border/60 p-3 xl:grid-cols-[1.2fr_1.2fr_1fr_1fr_auto]">
            <label className="grid gap-1.5">
              <Label className="font-mono-ui text-[0.7rem]">Discord user ID</Label>
              <Input
                value={row.user_id}
                placeholder="284102345871466496"
                onChange={(event) => onUpdate(index, { user_id: event.target.value })}
                autoComplete="off"
              />
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
              <Label className="font-mono-ui text-[0.7rem]">Governance roles</Label>
              <Input
                value={row.roles}
                placeholder="admin or operator"
                onChange={(event) => onUpdate(index, { roles: event.target.value })}
                autoComplete="off"
              />
            </label>
            <label className="grid gap-1.5">
              <Label className="font-mono-ui text-[0.7rem]">Teams</Label>
              <Input
                value={row.teams}
                placeholder="engineering, finance"
                onChange={(event) => onUpdate(index, { teams: event.target.value })}
                autoComplete="off"
              />
            </label>
            <Button
              size="xs"
              outlined
              className="self-end"
              onClick={() => onRemove(index)}
              disabled={disabled}
              aria-label="Remove Discord user"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ))}
      </div>

      <div className="mt-3 grid gap-2 text-xs normal-case leading-5 text-muted-foreground md:grid-cols-3">
        <div><strong>Multiple users:</strong> add one row per Discord ID; the saved env value is comma-separated automatically.</div>
        <div><strong>Normal users:</strong> use <code>operator</code> or <code>viewer</code> unless they need management abilities.</div>
        <div><strong>Admins:</strong> keep <code>admin</code> limited to people who can manage config, secrets, and access.</div>
      </div>
    </div>
  );
}
