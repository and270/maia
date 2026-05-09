import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  ExternalLink,
  MessageSquare,
  Play,
  RefreshCw,
  RotateCw,
  Save,
  ShieldCheck,
  Terminal,
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
import { api, type EnvVarInfo, type StatusResponse } from "@/lib/api";
import { PluginSlot } from "@/plugins";

type GatewayField = {
  key: string;
  label: string;
  placeholder?: string;
  secret?: boolean;
  required?: boolean;
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
      { key: "DISCORD_BOT_TOKEN", label: "Bot token", placeholder: "Discord bot token", secret: true, required: true },
      { key: "DISCORD_ALLOWED_USERS", label: "Allowed user IDs", placeholder: "284102345871466496" },
      { key: "DISCORD_ALLOWED_ROLES", label: "Allowed role IDs", placeholder: "123456789012345678" },
      { key: "DISCORD_HOME_CHANNEL", label: "Home channel", placeholder: "234567890123456789" },
    ],
    steps: [
      "Create an application in the Discord Developer Portal.",
      "Enable Message Content Intent, and Server Members Intent if using roles.",
      "Invite the bot with bot and applications.commands scopes.",
      "Copy user, role, and channel IDs with Developer Mode enabled.",
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
): string[] {
  const missing = platform.required.filter(
    (key) => !envIsSet(env, key) && !draft[key]?.trim(),
  );
  for (const group of platform.requiredAny ?? []) {
    const hasExisting = group.some((key) => envIsSet(env, key));
    const hasDraft = group.some((key) => draft[key]?.trim());
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
      const [nextEnv, nextStatus] = await Promise.all([
        api.getEnvVars(),
        api.getStatus(),
      ]);
      setEnv(nextEnv);
      setStatus(nextStatus);
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

  const savePlatform = async (platform: GatewayPlatform) => {
    const draft = drafts[platform.id] ?? {};
    const missing = missingRequirements(platform, env, draft);
    if (missing.length) {
      showToast(`Missing required gateway values: ${missing.join(", ")}`, "error");
      return;
    }

    const entries = Object.entries(draft)
      .map(([key, value]) => [key, value.trim()] as const)
      .filter(([, value]) => value.length > 0);

    if (!entries.length) {
      showToast("No new gateway values to save.", "success");
      return;
    }

    setBusy(`save:${platform.id}`);
    try {
      for (const [key, value] of entries) {
        await api.setEnvVar(key, value);
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
            "Test /dashboard from a private chat and approve access in Admin Access.",
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
                  {platform.fields.map((field) => {
                    const info = env[field.key];
                    const current = fieldStatus(env, field.key);
                    return (
                      <label key={field.key} className="grid gap-2">
                        <div className="flex items-center justify-between gap-2">
                          <Label className="font-mono-ui text-[0.7rem]">
                            {field.label}
                            {field.required ? " *" : ""}
                          </Label>
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
