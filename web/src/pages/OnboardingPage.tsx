import { useState } from "react";
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
import { api, type GovernanceWarning } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { PluginSlot } from "@/plugins";

function BaselineCard() {
  const { toast, showToast } = useToast();
  const [allowedRoles, setAllowedRoles] = useState("operator");
  const [approverRoles, setApproverRoles] = useState("manager");
  const [smart, setSmart] = useState(true);
  const [applying, setApplying] = useState(false);
  const [warnings, setWarnings] = useState<GovernanceWarning[] | null>(null);

  const toList = (value: string) =>
    value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);

  const apply = async () => {
    setApplying(true);
    try {
      const result = await api.applyGovernanceBaseline({
        terminal_allowed_roles: toList(allowedRoles),
        terminal_approver_roles: toList(approverRoles),
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
          governance enabled, <code>default_file_policy: deny</code>, terminal
          access restricted by role, flagged commands routed to an approver
          role, audit logging on, and (optionally) smart command approvals.
          Existing users, folder policies, teams, and roles are preserved.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label>Terminal allowed roles</Label>
            <Input
              value={allowedRoles}
              onChange={(event) => setAllowedRoles(event.target.value)}
              placeholder="operator"
            />
            <p className="text-xs text-muted-foreground">
              Who may run terminal/code at all. Comma-separated. Leave empty for
              no restriction.
            </p>
          </div>
          <div className="space-y-2">
            <Label>Command approver roles</Label>
            <Input
              value={approverRoles}
              onChange={(event) => setApproverRoles(event.target.value)}
              placeholder="manager"
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
                <Link to="/file-access" className="underline">
                  File Access
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

const STEPS = [
  {
    icon: ShieldCheck,
    title: "Tenant and governance",
    text: "Set governance.enabled, tenant_id, role_hierarchy, default_role, and production default_file_policy.",
    to: "/config?search=governance",
    action: "Open Config",
  },
  {
    icon: MessageSquare,
    title: "Messaging gateway",
    text: "Configure Slack, Discord, Mattermost, or Matrix credentials so users can talk to Maia from company channels.",
    to: "/gateway",
    action: "Open Gateway",
  },
  {
    icon: Users,
    title: "Dashboard access",
    text: "Approve /dashboard requests, assign roles and teams, and revoke dashboard login access from one operational page.",
    to: "/dashboard-access",
    action: "Open Access",
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
    to: "/file-access",
    action: "Open File Access",
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
    action: "Open Access",
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
  "Users can run /dashboard in a private chat to create a dashboard access request.",
  "Dashboard channel tokens are short-lived, one-use, approval-based, and revocable.",
  "Users that need shared team knowledge have governance.users.*.teams assigned.",
  "Production file policy is default deny.",
  "Corporate and team memories/skills are changed only through Knowledge approvals.",
  "Finance, HR, legal, security, shared folders, and delegated team roots have separate policies.",
  "Cron jobs that touch governed folders require manager or admin approval.",
  "Audit log retention and SIEM export are configured for regulated data.",
  "Migrated skills and MCP servers are reviewed before activation.",
];

export default function OnboardingPage() {
  return (
    <div className="flex flex-col gap-6">
      <PluginSlot name="onboarding:top" />

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone="outline">AmpliIA</Badge>
          <Badge tone="secondary">Maia</Badge>
        </div>
        <H2 variant="sm" className="flex items-center gap-2 text-muted-foreground">
          <ShieldCheck className="h-4 w-4" />
          Admin Onboarding
        </H2>
      </section>

      <BaselineCard />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {STEPS.map(({ action, icon: Icon, text, title, to }) => (
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
