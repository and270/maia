import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Clock,
  Database,
  FileKey2,
  FolderLock,
  KeyRound,
  MessageSquare,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Terminal,
  Users,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { H2 } from "@/components/NouiTypography";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toast } from "@/components/Toast";
import { SecureRuntimePanel } from "@/components/SecureRuntimePanel";
import { DashboardLoadingState } from "@/components/DashboardLoadingState";
import {
  api,
  type GovernanceSandboxStatus,
  type GovernanceWarning,
  type OnboardingProviderEntry,
  type OnboardingState,
} from "@/lib/api";
import { isDashboardEmbeddedChatEnabled } from "@/lib/dashboard-flags";
import { RoleMultiSelect } from "@/components/GovernanceFields";
import { useGovernanceOptions } from "@/hooks/useGovernanceOptions";
import { useToast } from "@/hooks/useToast";
import { PluginSlot } from "@/plugins";

// Providers most corporate installs reach for first; the rest of the catalog
// stays available under "More providers" in the same dropdown.
const FEATURED_PROVIDER_SLUGS = [
  "anthropic",
  "openrouter",
  "openai-codex",
  "gemini",
  "deepseek",
  "xai",
  "huggingface",
  "nvidia",
];

function StepMarker({ n, done }: { n: number; done: boolean }) {
  if (done) {
    return (
      <span className="flex h-7 w-7 shrink-0 items-center justify-center border border-success/50 bg-success/[0.08] text-success">
        <CheckCircle2 className="h-4 w-4" />
      </span>
    );
  }
  return (
    <span className="flex h-7 w-7 shrink-0 items-center justify-center border border-current/25 text-sm font-bold">
      {n}
    </span>
  );
}

function StepStatus({ done }: { done: boolean }) {
  return done ? (
    <Badge tone="outline" className="text-success border-success/40">
      Done
    </Badge>
  ) : (
    <Badge tone="outline" className="text-muted-foreground">
      Pending
    </Badge>
  );
}

const EFFORT_LABELS: Record<string, string> = {
  "": "Auto (provider default)",
  minimal: "Minimal — fastest",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "X-High — deepest reasoning",
};

function ProviderStepCard({
  state,
  onChanged,
}: {
  state: OnboardingState | null;
  onChanged: () => void;
}) {
  const { toast, showToast } = useToast();
  const [slug, setSlug] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [savingEffort, setSavingEffort] = useState(false);
  const chatEnabled = isDashboardEmbeddedChatEnabled();

  const catalog = useMemo(() => state?.providers_catalog ?? [], [state]);
  const featured = FEATURED_PROVIDER_SLUGS.map((s) =>
    catalog.find((p) => p.slug === s),
  ).filter((p): p is OnboardingProviderEntry => Boolean(p));
  const restKey = catalog.filter(
    (p) =>
      !FEATURED_PROVIDER_SLUGS.includes(p.slug) &&
      p.env_key &&
      p.auth_type === "api_key",
  );
  const restOther = catalog.filter(
    (p) =>
      !FEATURED_PROVIDER_SLUGS.includes(p.slug) &&
      !(p.env_key && p.auth_type === "api_key"),
  );
  const selected = catalog.find((p) => p.slug === slug) ?? null;
  const selectedNeedsKey = Boolean(
    selected && selected.env_key && selected.auth_type === "api_key",
  );
  const done = Boolean(state?.provider_configured);

  const save = async () => {
    if (!selected?.env_key || !apiKey.trim()) return;
    setSaving(true);
    try {
      await api.setEnvVar(selected.env_key, apiKey.trim());
      setApiKey("");
      showToast(`${selected.label} key saved`, "success");
      onChanged();
      window.dispatchEvent(new Event("maia:onboarding-updated"));
    } catch (err) {
      showToast(`Could not save key: ${err}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const saveEffort = async (effort: string) => {
    setSavingEffort(true);
    try {
      await api.setReasoningEffort(effort);
      showToast(
        effort ? `Reasoning effort set to ${effort}` : "Reasoning effort set to auto",
        "success",
      );
      onChanged();
    } catch (err) {
      showToast(`Could not set effort: ${err}`, "error");
    } finally {
      setSavingEffort(false);
    }
  };

  return (
    <Card>
      <Toast toast={toast} />
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2 text-sm">
          <span className="flex items-center gap-3">
            <StepMarker n={1} done={done} />
            <KeyRound className="h-4 w-4" />
            Choose your model provider
          </span>
          <StepStatus done={done} />
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 normal-case">
        {done ? (
          <>
            <div className="flex items-start gap-2 border border-success/40 bg-success/[0.06] p-3">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
              <p className="text-sm leading-6 text-success">
                Provider ready
                {state?.current_provider ? `: ${state.current_provider}` : ""}
                {state?.current_model ? ` · ${state.current_model}` : ""}.
                {!state?.current_model &&
                  " No main model pinned yet, a recommended default is used until you pick one."}
              </p>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Reasoning effort</Label>
                <select
                  value={state?.current_effort ?? ""}
                  onChange={(event) => void saveEffort(event.target.value)}
                  disabled={savingEffort}
                  className="h-9 w-full border border-border bg-background px-2 text-sm"
                >
                  {["", ...(state?.valid_efforts ?? [])].map((effort) => (
                    <option key={effort || "auto"} value={effort}>
                      {EFFORT_LABELS[effort] ?? effort}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  How hard reasoning models think before answering. Applies to
                  new sessions; models without reasoning ignore it.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              {chatEnabled ? (
                <Link
                  to="/chat"
                  className="inline-flex w-fit items-center gap-2 border border-current/25 px-3 py-2 text-xs font-bold uppercase tracking-[0.08em] text-midground transition-opacity hover:opacity-80"
                >
                  <MessageSquare className="h-3.5 w-3.5" />
                  Try it in Chat
                </Link>
              ) : (
                <span className="inline-flex items-center gap-2 text-muted-foreground">
                  <Terminal className="h-3.5 w-3.5" />
                  Test it now: run <code>maia</code> in your terminal
                </span>
              )}
              <Link
                to="/models"
                className="inline-flex w-fit items-center gap-2 border border-current/25 px-3 py-2 text-xs font-bold uppercase tracking-[0.08em] text-midground transition-opacity hover:opacity-80"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Pick or change models
              </Link>
              <Link to="/env" className="text-muted-foreground underline">
                Manage keys
              </Link>
            </div>
          </>
        ) : (
          <>
            <p className="text-sm leading-6 text-muted-foreground">
              Maia needs one working model provider before anything else. Pick a
              provider, paste its API key, and you can start chatting
              immediately, everything later (gateway, governance, cron) builds
              on this.
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Provider</Label>
                <select
                  value={slug}
                  onChange={(event) => setSlug(event.target.value)}
                  className="h-9 w-full border border-border bg-background px-2 text-sm"
                >
                  <option value="">Select a provider…</option>
                  {featured.length > 0 && (
                    <optgroup label="Popular">
                      {featured.map((p) => (
                        <option key={p.slug} value={p.slug}>
                          {p.label}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {restKey.length > 0 && (
                    <optgroup label="More providers (API key)">
                      {restKey.map((p) => (
                        <option key={p.slug} value={p.slug}>
                          {p.label}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {restOther.length > 0 && (
                    <optgroup label="OAuth / local sign-in">
                      {restOther.map((p) => (
                        <option key={p.slug} value={p.slug}>
                          {p.label}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
                {selected && (
                  <p className="text-xs text-muted-foreground">
                    {selected.description}
                    {selectedNeedsKey && (
                      <>
                        {" "}
                        (stored as <code>{selected.env_key}</code> in the
                        managed .env)
                      </>
                    )}
                  </p>
                )}
              </div>
              {selectedNeedsKey || !selected ? (
                <div className="space-y-2">
                  <Label>API key</Label>
                  <Input
                    type="password"
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    placeholder={
                      selected ? `${selected.env_key} value` : "Select a provider first"
                    }
                    disabled={!selected}
                  />
                  <p className="text-xs text-muted-foreground">
                    Keys live in the managed credential store, never in
                    prompts, memories, or skills.
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  <Label>Sign in</Label>
                  <div className="flex items-start gap-2 border border-border bg-background p-3">
                    <Terminal className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                    <p className="text-xs leading-5 normal-case text-muted-foreground">
                      {selected?.label} signs in without a pasted key (OAuth,
                      device login, or a local server). In a terminal run{" "}
                      <code>maia model</code>, pick {selected?.label}, complete
                      the sign-in, then click Refresh here.
                    </p>
                  </div>
                  <Button onClick={onChanged} size="sm" className="w-fit">
                    Refresh status
                  </Button>
                </div>
              )}
            </div>
            {(selectedNeedsKey || !selected) && (
              <Button
                onClick={save}
                disabled={!selected || !apiKey.trim() || saving}
                size="sm"
                className="w-fit"
              >
                <KeyRound className="h-4 w-4" />
                {saving ? "Saving…" : "Save key"}
              </Button>
            )}
            <p className="text-xs leading-5 text-muted-foreground">
              OpenAI GPT models: pick <strong>OpenAI Codex</strong> above
              (ChatGPT/Codex OAuth sign-in) or use OpenRouter with an API key.
              Local models (Ollama, LM Studio) and custom endpoints:{" "}
              <code>maia model</code> in a terminal or open{" "}
              <Link to="/models" className="underline">
                Models
              </Link>
              .
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function StepLinkCard({
  n,
  done,
  icon: Icon,
  title,
  text,
  to,
  action,
}: {
  n: number;
  done: boolean;
  icon: typeof MessageSquare;
  title: string;
  text: string;
  to: string;
  action: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2 text-sm">
          <span className="flex items-center gap-3">
            <StepMarker n={n} done={done} />
            <Icon className="h-4 w-4" />
            {title}
          </span>
          <StepStatus done={done} />
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 normal-case">
        <p className="text-sm leading-6 text-muted-foreground">{text}</p>
        <Link
          to={to}
          className="inline-flex w-fit items-center gap-2 border border-current/25 px-3 py-2 text-xs font-bold uppercase tracking-[0.08em] text-midground transition-opacity hover:opacity-80"
        >
          <BookOpen className="h-3.5 w-3.5" />
          {action}
        </Link>
      </CardContent>
    </Card>
  );
}

function BaselineCard() {
  const { toast, showToast } = useToast();
  const { roles: roleOptions } = useGovernanceOptions();
  const [allowedRoles, setAllowedRoles] = useState<string[]>(["operator"]);
  const [approverRoles, setApproverRoles] = useState<string[]>(["manager"]);
  const [smart, setSmart] = useState(true);
  const [applying, setApplying] = useState(false);
  const [warnings, setWarnings] = useState<GovernanceWarning[] | null>(null);

  const apply = async () => {
    setApplying(true);
    try {
      const result = await api.applyGovernanceBaseline({
        terminal_allowed_roles: allowedRoles,
        terminal_approver_roles: approverRoles,
        smart_approvals: smart,
      });
      setWarnings(result.warnings ?? []);
      showToast("Corporate governance baseline applied", "success");
    } catch (err) {
      showToast(`Could not apply baseline: ${err}`, "error");
    } finally {
      setApplying(false);
    }
  };

  return (
    <Card>
      <Toast toast={toast} />
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Sparkles className="h-4 w-4" />
          Apply corporate security baseline
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 normal-case">
        <p className="text-sm leading-6 text-muted-foreground">
          Sets the recommended least-privilege posture in one step:
          governance enabled, immutable deny-by-default file access, terminal
          access restricted by role, flagged commands routed to an approver
          role, audit logging on, and (optionally) smart command approvals.
          Existing users, folder policies, teams, and roles are preserved.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label>Terminal allowed roles</Label>
            <RoleMultiSelect
              value={allowedRoles}
              onChange={setAllowedRoles}
              options={roleOptions}
              emptyHint="none selected = no restriction"
            />
            <p className="text-xs text-muted-foreground">
              Who may run terminal/code at all. Leave all unselected for no
              restriction.
            </p>
          </div>
          <div className="space-y-2">
            <Label>Command approver roles</Label>
            <RoleMultiSelect
              value={approverRoles}
              onChange={setApproverRoles}
              options={roleOptions}
              emptyHint="pick who approves flagged commands"
            />
            <p className="text-xs text-muted-foreground">
              Who must approve flagged commands from non-approvers. The
              requester can no longer self-approve.
            </p>
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={smart}
            onChange={(event) => setSmart(event.target.checked)}
          />
          Enable smart command approvals (auxiliary model auto-clears false
          positives; requires a working model)
        </label>
        <Button onClick={apply} disabled={applying} size="sm" className="w-fit">
          <Sparkles className="h-4 w-4" />
          Apply baseline
        </Button>

        {warnings !== null && warnings.length === 0 && (
          <div className="flex items-start gap-2 border border-success/40 bg-success/[0.06] p-3">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
            <p className="text-sm leading-6 text-success">
              Baseline applied and no posture gaps remain.
            </p>
          </div>
        )}
        {warnings !== null && warnings.length > 0 && (
          <div className="flex items-start gap-2 border border-warning/40 bg-warning/[0.06] p-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <div className="flex flex-col gap-1 min-w-0">
              <p className="text-sm font-semibold text-warning">
                Applied — but finish these to close the gaps:
              </p>
              {warnings.map((warning) => (
                <p key={warning.code} className="text-xs leading-5 text-warning/80">
                  {warning.message}
                </p>
              ))}
              <p className="text-xs leading-5 text-muted-foreground">
                Add scoped grants in{" "}
                <Link to="/governance?section=files" className="underline">
                  Governance / File access
                </Link>
                .
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const NEXT_STEPS = [
  {
    icon: ShieldCheck,
    title: "Tenant and governance",
    text: "Fine-tune the tenant, role hierarchy, people, teams, and explicit file policies.",
    to: "/governance?section=settings",
    action: "Open Governance",
  },
  {
    icon: Database,
    title: "Knowledge layers",
    text: "Review corporate, team, and user memory/skills, then approve shared corporate/team proposals by role.",
    to: "/knowledge",
    action: "Open Knowledge",
  },
  {
    icon: FolderLock,
    title: "Folder access",
    text: "Set default deny, add company roots, then grant read/write access by role, team, or exact user under delegated folders.",
    to: "/governance?section=files",
    action: "Open file policies",
  },
  {
    icon: Clock,
    title: "Cron approvals",
    text: "Create scheduled jobs with authorization checkpoints and approve or deny pending runs by role or user.",
    to: "/cron",
    action: "Open Cron",
  },
  {
    icon: ScrollText,
    title: "Audit trail",
    text: "Review governance denials and cron authorization events in audit.jsonl before connecting a SIEM webhook.",
    to: "/logs",
    action: "View Logs",
  },
  {
    icon: FileKey2,
    title: "Channel dashboard tokens",
    text: "Keep channel tokens short-lived and approval-based so users get one-time login tokens only after admin review.",
    to: "/dashboard-access",
    action: "Open Dashboard Access",
  },
  {
    icon: FileKey2,
    title: "Hermes migration",
    text: "Import upstream Hermes tar/tar.gz exports with guarded migration mode, then review staged skills and secrets.",
    to: "/docs",
    action: "Read Docs",
  },
];

const CHECKLIST = [
  "Gateway users are identified by platform:user_id.",
  "Every human gateway user has an explicit governance.users role before first bot access.",
  "Allowlisted users without Governance membership remain blocked and cannot create dashboard requests.",
  "Dashboard channel tokens are short-lived, one-use, approval-based, and revocable.",
  "Users that need shared team knowledge have governance.users.*.teams assigned.",
  "Production file policy is default deny.",
  "Personal memories and skills are isolated by platform:user_id; shared layers use Knowledge approvals.",
  "Finance, HR, legal, security, shared folders, and delegated team roots have separate policies.",
  "Cron jobs that touch governed folders require manager or admin approval.",
  "Audit log retention and SIEM export are configured for regulated data.",
  "Migrated skills and MCP servers are reviewed before activation.",
];

export default function OnboardingPage() {
  const [state, setState] = useState<OnboardingState | null>(null);
  const [stateLoading, setStateLoading] = useState(true);
  const [runtimeStatus, setRuntimeStatus] = useState<GovernanceSandboxStatus | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(true);
  const { toast: runtimeToast, showToast: showRuntimeToast } = useToast();

  const refresh = useCallback(() => {
    api
      .getOnboardingState()
      .then(setState)
      .catch(() => setState(null))
      .finally(() => setStateLoading(false));
    api
      .getSecureRuntimeStatus()
      .then(setRuntimeStatus)
      .catch(() => setRuntimeStatus(null))
      .finally(() => setRuntimeLoading(false));
  }, []);

  const finishRuntimeSetup = useCallback(async () => {
    setRuntimeLoading(true);
    try {
      const nextStatus = await api.provisionSecureRuntime();
      setRuntimeStatus(nextStatus);
      showRuntimeToast("Secure runtime is ready", "success");
    } catch (error) {
      showRuntimeToast(`Could not finish secure runtime setup: ${error}`, "error");
    } finally {
      setRuntimeLoading(false);
    }
  }, [showRuntimeToast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if ((stateLoading && !state) || (runtimeLoading && !runtimeStatus)) {
    return (
      <div className="flex flex-col gap-6">
        <PluginSlot name="onboarding:top" />
        <Toast toast={runtimeToast} />
        <DashboardLoadingState
          title="Restoring your onboarding progress"
          description="Checking saved provider, Gateway, Governance, dashboard access, and secure runtime status before marking any step pending or ready."
          cards={4}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PluginSlot name="onboarding:top" />
      <Toast toast={runtimeToast} />

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone="outline">AmpliIA</Badge>
          <Badge tone="secondary">Maia</Badge>
        </div>
        <H2 variant="sm" className="flex items-center gap-2 text-muted-foreground">
          <ShieldCheck className="h-4 w-4" />
          Setup and Onboarding
        </H2>
        <p className="text-sm normal-case leading-6 text-muted-foreground">
          Work through the numbered steps in order: model provider first (so
          Maia can answer at all), then the messaging gateway (so your team can
          reach it), then governance and dashboard access (so it is safe to
          share), then the secure runtime for full governed terminal and code
          automation. Maia remains safe in Restricted mode if that final system
          dependency is not ready yet.
        </p>
      </section>

      <ProviderStepCard state={state} onChanged={refresh} />

      <StepLinkCard
        n={2}
        done={Boolean(state?.gateway_configured)}
        icon={MessageSquare}
        title="Connect a messaging gateway"
        text="Configure Slack, Discord, Mattermost, Matrix, Telegram, or WhatsApp credentials so your team can talk to Maia from company channels. Then install the gateway service so it stays online."
        to="/gateway?from=onboarding"
        action="Open Gateway"
      />

      <StepLinkCard
        n={3}
        done={Boolean(state?.governance_configured)}
        icon={Users}
        title="Set up governance and dashboard access"
        text="Use Gateway's guided person setup to add at least one non-admin teammate with a role and explicit direct or team file access. Governance remains available for advanced review; the bootstrap administrator alone does not complete this step."
        to="/governance?from=onboarding"
        action="Open Governance"
      />

      {runtimeStatus && (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="flex items-center gap-3">
                <StepMarker n={4} done={runtimeStatus.ready} />
                <Terminal className="h-4 w-4" />
                Enable full governed automation
              </span>
              <Badge
                tone={runtimeStatus.ready ? "outline" : "warning"}
                className={runtimeStatus.ready ? "border-success/40 text-success" : ""}
              >
                {runtimeStatus.ready ? "Done" : "Recommended"}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <SecureRuntimePanel
              status={runtimeStatus}
              loading={runtimeLoading}
              defaultExpanded
              onSetup={() => void finishRuntimeSetup()}
              onRefresh={() => {
                setRuntimeLoading(true);
                refresh();
              }}
            />
          </CardContent>
        </Card>
      )}

      <BaselineCard />

      <section className="flex flex-col gap-3">
        <H2 variant="sm" className="text-muted-foreground">
          Next steps
        </H2>
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          {NEXT_STEPS.map(({ action, icon: Icon, text, title, to }) => (
            <Card key={title}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <Icon className="h-4 w-4" />
                  {title}
                </CardTitle>
              </CardHeader>
              <CardContent className="flex min-h-40 flex-col justify-between gap-4">
                <p className="text-sm normal-case leading-6 text-muted-foreground">
                  {text}
                </p>
                <Link
                  to={to}
                  className="inline-flex w-fit items-center gap-2 border border-current/25 px-3 py-2 text-xs font-bold uppercase tracking-[0.08em] text-midground transition-opacity hover:opacity-80"
                >
                  <BookOpen className="h-3.5 w-3.5" />
                  {action}
                </Link>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <CheckCircle2 className="h-4 w-4" />
            Launch Checklist
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {CHECKLIST.map((item) => (
              <div
                key={item}
                className="flex min-w-0 items-start gap-2 text-sm normal-case leading-6 text-muted-foreground"
              >
                <CheckCircle2 className="mt-1 h-3.5 w-3.5 shrink-0 text-success" />
                <span>{item}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <KeyRound className="h-4 w-4" />
            Migration Command
          </CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="overflow-auto rounded-sm border border-border bg-black/30 p-3 font-mono-ui text-xs normal-case text-foreground">
            maia import ~/Downloads/hermes-export.tar.gz --from-hermes-export
          </pre>
        </CardContent>
      </Card>

      <PluginSlot name="onboarding:bottom" />
    </div>
  );
}
