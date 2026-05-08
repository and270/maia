import {
  BookOpen,
  CheckCircle2,
  Clock,
  Database,
  FileKey2,
  FolderLock,
  KeyRound,
  ScrollText,
  ShieldCheck,
  Users,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { H2 } from "@/components/NouiTypography";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PluginSlot } from "@/plugins";

const STEPS = [
  {
    icon: ShieldCheck,
    title: "Tenant and governance",
    text: "Set governance.enabled, tenant_id, role_hierarchy, default_role, and production default_file_policy.",
    to: "/config?search=governance",
    action: "Open Config",
  },
  {
    icon: Users,
    title: "Users and roles",
    text: "Ask users for /whoami, then map identities such as slack:U123, discord:99887766, or whatsapp:+15551234567 to roles and teams.",
    to: "/config?search=governance.users",
    action: "Assign Roles",
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
    text: "Configure dashboard.auth.channel_tokens so mapped users can request /dashboard one-time tokens from private channel chats.",
    to: "/config?search=dashboard.auth.channel_tokens",
    action: "Open Config",
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
  "Gateway users are mapped by platform:user_id.",
  "Users can run /whoami to reveal the exact identity key admins should map.",
  "Dashboard channel tokens are enabled only with short TTL and private/direct chat requests.",
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
          <Badge tone="secondary">Coorporate Hermes</Badge>
        </div>
        <H2 variant="sm" className="flex items-center gap-2 text-muted-foreground">
          <ShieldCheck className="h-4 w-4" />
          Admin Onboarding
        </H2>
      </section>

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
            coorporate import ~/Downloads/hermes-export.tar.gz --from-hermes-export
          </pre>
        </CardContent>
      </Card>

      <PluginSlot name="onboarding:bottom" />
    </div>
  );
}
