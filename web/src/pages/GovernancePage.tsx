import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  FileCheck,
  FolderTree,
  RefreshCw,
  Save,
  Search,
  Settings2,
  Shield,
  Trash2,
  Users,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { RoleMultiSelect, TeamsInput } from "@/components/GovernanceFields";
import { H2 } from "@/components/NouiTypography";
import { Toast } from "@/components/Toast";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/useToast";
import { api, type GovernanceOverview, type GovernanceUser } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PluginSlot } from "@/plugins";
import FileAccessPage from "@/pages/FileAccessPage";
import FileApprovalsPage from "@/pages/FileApprovalsPage";

const SECTIONS = ["people", "files", "approvals", "settings"] as const;
type GovernanceSection = (typeof SECTIONS)[number];

const SECTION_META: Record<
  GovernanceSection,
  { label: string; icon: typeof Users; description: string }
> = {
  people: {
    label: "People",
    icon: Users,
    description: "Gateway identities, roles, teams, and access state.",
  },
  files: {
    label: "File access",
    icon: FolderTree,
    description: "Paths, read/write grants, exceptions, and approval gates.",
  },
  approvals: {
    label: "Approvals",
    icon: FileCheck,
    description: "Review staged file changes before they are applied.",
  },
  settings: {
    label: "Settings",
    icon: Settings2,
    description: "Tenant-wide roles, defaults, sessions, terminal, and cron.",
  },
};

function textToList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item, index, all) => Boolean(item) && all.indexOf(item) === index);
}

function roleTone(role: string): "secondary" | "warning" | "success" | "outline" {
  if (role === "admin") return "warning";
  if (role === "manager") return "success";
  if (role === "operator") return "secondary";
  return "outline";
}

function UserStatus({ user }: { user: GovernanceUser }) {
  if (!user.governed) return <Badge tone="warning">Pending Governance</Badge>;
  if (user.gateway_allowed) return <Badge tone="success">Bot access active</Badge>;
  return <Badge tone="secondary">Governed identity</Badge>;
}

type UserDraft = { name: string; roles: string[]; teams: string };

function PeopleWorkspace({
  overview,
  reload,
}: {
  overview: GovernanceOverview;
  reload: () => Promise<void>;
}) {
  const [params, setParams] = useSearchParams();
  const requestedKey = params.get("user") ?? "";
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | "pending" | "active">("all");
  const [selectedKey, setSelectedKey] = useState(requestedKey);
  const [draft, setDraft] = useState<UserDraft>({ name: "", roles: [], teams: "" });
  const [busy, setBusy] = useState(false);
  const { toast, showToast } = useToast();

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return overview.users.filter((user) => {
      if (status === "pending" && user.governed) return false;
      if (status === "active" && !user.governed) return false;
      if (!needle) return true;
      return [user.actor_key, user.name, user.platform, ...user.roles, ...user.teams]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [overview.users, query, status]);

  const selected =
    overview.users.find((user) => user.actor_key === selectedKey) ?? filtered[0] ?? null;

  useEffect(() => {
    if (!selected) return;
    // Keep the inspector draft aligned when the selected identity changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft({
      name: selected.name,
      roles: selected.roles,
      teams: selected.teams.join(", "),
    });
  }, [selected]);

  const selectUser = (actorKey: string) => {
    setSelectedKey(actorKey);
    const next = new URLSearchParams(params);
    next.set("section", "people");
    next.set("user", actorKey);
    setParams(next, { replace: true });
  };

  const save = async () => {
    if (!selected) return;
    if (draft.roles.length === 0) {
      showToast("Select at least one role before granting access.", "error");
      return;
    }
    setBusy(true);
    try {
      await api.saveGovernanceUser(selected.actor_key, {
        name: draft.name.trim(),
        roles: draft.roles,
        teams: textToList(draft.teams),
      });
      showToast(`${selected.actor_key} is active in Governance.`, "success");
      await reload();
    } catch (error) {
      showToast(`Could not save user: ${error}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!selected?.governed) return;
    if (
      !window.confirm(
        `Remove ${selected.actor_key} from Governance? Gateway admission is preserved, but the user will be blocked from Maia.`,
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await api.removeGovernanceUser(selected.actor_key);
      showToast(`${selected.actor_key} is now pending Governance.`, "success");
      await reload();
    } catch (error) {
      showToast(`Could not remove Governance access: ${error}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const pendingCount = overview.users.filter((user) => !user.governed).length;
  const roleCounts = overview.role_hierarchy.map((role) => ({
    role,
    count: overview.users.filter((user) => user.roles.includes(role)).length,
  }));

  return (
    <div className="grid min-h-[34rem] gap-0 border border-border lg:grid-cols-[minmax(18rem,0.9fr)_minmax(26rem,1.5fr)]">
      <Toast toast={toast} />
      <section className="border-b border-border bg-muted/10 lg:border-b-0 lg:border-r">
        <div className="space-y-3 border-b border-border p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold normal-case">People</div>
              <div className="text-xs normal-case text-muted-foreground">
                {overview.users.length} identities · {pendingCount} pending
              </div>
            </div>
            <Button size="icon" ghost onClick={() => void reload()} aria-label="Refresh users">
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search identity, name, role, or team"
              className="pl-8"
            />
          </div>
          <div className="flex gap-1">
            {(["all", "pending", "active"] as const).map((filter) => (
              <Button
                key={filter}
                size="xs"
                ghost={status !== filter}
                onClick={() => setStatus(filter)}
              >
                {filter}
              </Button>
            ))}
          </div>
        </div>
        <div className="max-h-[54rem] overflow-y-auto">
          {filtered.map((user) => (
            <button
              key={user.actor_key}
              type="button"
              onClick={() => selectUser(user.actor_key)}
              className={cn(
                "grid w-full gap-2 border-b border-border/70 px-4 py-3 text-left normal-case transition-colors",
                selected?.actor_key === user.actor_key
                  ? "bg-primary/10 text-foreground"
                  : "hover:bg-muted/30",
              )}
            >
              <div className="flex min-w-0 items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{user.name || user.actor_key}</div>
                  <div className="truncate font-mono-ui text-[0.7rem] text-muted-foreground">
                    {user.actor_key}
                  </div>
                </div>
                <UserStatus user={user} />
              </div>
              <div className="flex flex-wrap gap-1">
                {user.roles.map((role) => (
                  <Badge key={role} tone={roleTone(role)}>{role}</Badge>
                ))}
                {user.teams.map((team) => (
                  <Badge key={team} tone="outline">team: {team}</Badge>
                ))}
              </div>
            </button>
          ))}
          {filtered.length === 0 && (
            <div className="p-6 text-center text-sm normal-case text-muted-foreground">
              No matching identities.
            </div>
          )}
        </div>
      </section>

      <section className="min-w-0 p-5 lg:p-6">
        {selected ? (
          <div className="space-y-7">
            <div className="flex flex-col gap-3 border-b border-border pb-5 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <H2 variant="sm" className="normal-case text-foreground">
                    {selected.name || selected.actor_key}
                  </H2>
                  <UserStatus user={selected} />
                </div>
                <p className="mt-1 font-mono-ui text-xs text-muted-foreground">{selected.actor_key}</p>
              </div>
              <div className="flex gap-2">
                {selected.governed && (
                  <Button size="sm" ghost onClick={remove} disabled={busy}>
                    <Trash2 className="h-4 w-4" />
                    Remove access
                  </Button>
                )}
                <Button size="sm" onClick={save} disabled={busy}>
                  {busy ? <Spinner className="h-4 w-4" /> : <Save className="h-4 w-4" />}
                  {selected.governed ? "Save changes" : "Grant access"}
                </Button>
              </div>
            </div>

            {!selected.governed && (
              <div className="border-l-2 border-warning bg-warning/5 px-4 py-3 text-sm normal-case leading-6 text-muted-foreground">
                This identity is admitted by {selected.platform}, but remains blocked from Maia until an
                administrator grants at least one role here.
              </div>
            )}

            <div className="grid gap-5 xl:grid-cols-2">
              <label className="grid gap-2 normal-case">
                <Label>Display name</Label>
                <Input
                  value={draft.name}
                  onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                  placeholder={selected.actor_key}
                />
                <span className="text-xs text-muted-foreground">Used in audit and administration views.</span>
              </label>
              <div className="grid gap-2 normal-case">
                <Label>Teams</Label>
                <TeamsInput
                  value={draft.teams}
                  onChange={(teams) => setDraft((current) => ({ ...current, teams }))}
                  options={overview.teams}
                  listId={`governance-teams-${selected.user_id.replace(/[^a-z0-9]/gi, "-")}`}
                />
                <span className="text-xs text-muted-foreground">
                  Teams control shared knowledge and can receive file grants.
                </span>
              </div>
            </div>

            <div className="grid gap-2 normal-case">
              <Label>Roles</Label>
              <RoleMultiSelect
                value={draft.roles}
                onChange={(roles) => setDraft((current) => ({ ...current, roles }))}
                options={overview.role_hierarchy}
                emptyHint="Select a role to grant access"
              />
              <span className="text-xs leading-5 text-muted-foreground">
                Later roles inherit earlier roles in the configured hierarchy. Assign the narrowest role that
                covers this person&apos;s work.
              </span>
            </div>

            <div className="grid gap-3 border-t border-border pt-5 sm:grid-cols-2">
              <div className="space-y-1 normal-case">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Bot access</div>
                <div className="text-sm">
                  {selected.gateway_allowed
                    ? selected.governed
                      ? "Allowed by the gateway and Governance"
                      : "Gateway admitted; Governance pending"
                    : "Not present in a managed gateway allowlist"}
                </div>
              </div>
              <div className="space-y-1 normal-case">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Dashboard access</div>
                <div className="text-sm text-muted-foreground">
                  Dashboard login is approved separately in{" "}
                  <Link to="/dashboard-access" className="font-semibold text-primary hover:underline">
                    Dashboard Access
                  </Link>
                  .
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex min-h-80 items-center justify-center text-sm normal-case text-muted-foreground">
            Add a user in Gateway, then return here to grant a role.
          </div>
        )}
      </section>

      <section className="border-t border-border p-4 lg:col-span-2">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Role coverage
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-2 normal-case text-sm">
          {roleCounts.map(({ role, count }) => (
            <span key={role} className="flex items-center gap-2">
              <Badge tone={roleTone(role)}>{role}</Badge>
              <span className="text-muted-foreground">{count} people</span>
            </span>
          ))}
        </div>
      </section>
    </div>
  );
}

function SettingsWorkspace({
  overview,
  reload,
}: {
  overview: GovernanceOverview;
  reload: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(overview);
  const [busy, setBusy] = useState(false);
  const { toast, showToast } = useToast();

  useEffect(() => {
    // Refresh the form after a successful save/reload from the server.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft(overview);
  }, [overview]);

  const save = async () => {
    setBusy(true);
    try {
      await api.saveGovernanceSettings({
        enabled: draft.enabled,
        tenant_id: draft.tenant_id,
        default_role: draft.default_role,
        role_hierarchy: draft.role_hierarchy,
        default_file_policy: draft.default_file_policy,
        team_file_manager_roles: draft.team_file_manager_roles,
        gateway_group_sessions_per_user: draft.gateway.group_sessions_per_user,
        gateway_thread_sessions_per_user: draft.gateway.thread_sessions_per_user,
        cron_default_authorizer_roles: draft.cron.default_authorizer_roles,
        terminal_allowed_roles: draft.terminal.allowed_roles,
        terminal_approver_roles: draft.terminal.approver_roles,
      });
      showToast("Governance settings saved.", "success");
      await reload();
    } catch (error) {
      showToast(`Could not save Governance settings: ${error}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const roleList = draft.role_hierarchy;
  const roleSetting = (
    label: string,
    value: string[],
    onChange: (roles: string[]) => void,
    help: string,
  ) => (
    <div className="grid gap-2 normal-case">
      <Label>{label}</Label>
      <RoleMultiSelect value={value} onChange={onChange} options={roleList} emptyHint="No roles selected" />
      <p className="text-xs leading-5 text-muted-foreground">{help}</p>
    </div>
  );

  return (
    <div className="space-y-5">
      <Toast toast={toast} />
      <div className="flex items-start justify-between gap-4 border-b border-border pb-4">
        <div>
          <h3 className="text-sm font-semibold normal-case">Tenant-wide governance</h3>
          <p className="mt-1 max-w-3xl text-xs normal-case leading-5 text-muted-foreground">
            These controls change authorization for every gateway identity. Role removal is blocked while the role
            is still assigned to a user, file policy, team root, terminal gate, or cron gate.
          </p>
        </div>
        <Button size="sm" onClick={save} disabled={busy}>
          {busy ? <Spinner className="h-4 w-4" /> : <Save className="h-4 w-4" />}
          Save settings
        </Button>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Tenant and roles</CardTitle></CardHeader>
          <CardContent className="grid gap-5 normal-case">
            <label className="flex items-start justify-between gap-4">
              <span>
                <span className="block text-sm font-medium">Governance enabled</span>
                <span className="mt-1 block text-xs text-muted-foreground">Fail closed for human gateway users.</span>
              </span>
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))}
              />
            </label>
            <label className="grid gap-2">
              <Label>Tenant ID</Label>
              <Input value={draft.tenant_id} onChange={(event) => setDraft((current) => ({ ...current, tenant_id: event.target.value }))} />
            </label>
            <label className="grid gap-2">
              <Label>Ordered role hierarchy</Label>
              <Input
                value={draft.role_hierarchy.join(", ")}
                onChange={(event) => {
                  const roles = textToList(event.target.value);
                  setDraft((current) => ({
                    ...current,
                    role_hierarchy: roles,
                    default_role: roles.includes(current.default_role) ? current.default_role : roles[0] ?? "",
                  }));
                }}
                placeholder="viewer, operator, manager, admin"
              />
              <span className="text-xs text-muted-foreground">Later roles inherit every earlier role.</span>
            </label>
            <label className="grid gap-2">
              <Label>Default role</Label>
              <select
                value={draft.default_role}
                onChange={(event) => setDraft((current) => ({ ...current, default_role: event.target.value }))}
                className="h-10 border border-border bg-background px-3 text-sm"
              >
                {roleList.map((role) => <option key={role} value={role}>{role}</option>)}
              </select>
            </label>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>File and team defaults</CardTitle></CardHeader>
          <CardContent className="grid gap-5">
            <label className="grid gap-2 normal-case">
              <Label>Unmatched file paths</Label>
              <select
                value={draft.default_file_policy}
                onChange={(event) => setDraft((current) => ({ ...current, default_file_policy: event.target.value }))}
                className="h-10 border border-border bg-background px-3 text-sm"
              >
                <option value="deny">Deny — recommended for production</option>
                <option value="allow">Allow — compatibility mode</option>
              </select>
            </label>
            {roleSetting(
              "Roles that may manage delegated team roots",
              draft.team_file_manager_roles,
              (roles) => setDraft((current) => ({ ...current, team_file_manager_roles: roles })),
              "These users remain limited to the server roots delegated to their teams.",
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Gateway session isolation</CardTitle></CardHeader>
          <CardContent className="grid gap-4 normal-case text-sm">
            <Toggle
              label="Separate regular group sessions per user"
              help="Recommended: each person in a shared channel keeps an independent conversation."
              checked={draft.gateway.group_sessions_per_user}
              onChange={(checked) => setDraft((current) => ({ ...current, gateway: { ...current.gateway, group_sessions_per_user: checked } }))}
            />
            <Toggle
              label="Separate explicit threads per user"
              help="Usually disabled so participants in a thread share its context."
              checked={draft.gateway.thread_sessions_per_user}
              onChange={(checked) => setDraft((current) => ({ ...current, gateway: { ...current.gateway, thread_sessions_per_user: checked } }))}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Human authorization</CardTitle></CardHeader>
          <CardContent className="grid gap-5">
            {roleSetting(
              "Terminal allowed roles",
              draft.terminal.allowed_roles,
              (roles) => setDraft((current) => ({ ...current, terminal: { ...current.terminal, allowed_roles: roles } })),
              "Empty preserves the current unrestricted terminal-role behavior.",
            )}
            {roleSetting(
              "Terminal approver roles",
              draft.terminal.approver_roles,
              (roles) => setDraft((current) => ({ ...current, terminal: { ...current.terminal, approver_roles: roles } })),
              "Flagged commands from other roles wait for one of these approvers.",
            )}
            {roleSetting(
              "Default cron authorizer roles",
              draft.cron.default_authorizer_roles,
              (roles) => setDraft((current) => ({ ...current, cron: { default_authorizer_roles: roles } })),
              "Used when a cron authorization checkpoint does not name its own roles.",
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Toggle({
  label,
  help,
  checked,
  onChange,
}: {
  label: string;
  help: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-start justify-between gap-4">
      <span>
        <span className="block font-medium">{label}</span>
        <span className="mt-1 block text-xs leading-5 text-muted-foreground">{help}</span>
      </span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

export default function GovernancePage() {
  const [params, setParams] = useSearchParams();
  const rawSection = params.get("section") as GovernanceSection | null;
  const section = rawSection && SECTIONS.includes(rawSection) ? rawSection : "people";
  const [overview, setOverview] = useState<GovernanceOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const { toast, showToast } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setOverview(await api.getGovernanceOverview());
    } catch (error) {
      showToast(`Failed to load Governance: ${error}`, "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    // Initial remote state load.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const selectSection = (nextSection: GovernanceSection) => {
    const next = new URLSearchParams(params);
    next.set("section", nextSection);
    if (nextSection !== "people") next.delete("user");
    setParams(next);
  };

  if (loading && !overview) {
    return <div className="flex items-center justify-center py-24"><Spinner className="text-2xl text-primary" /></div>;
  }

  if (!overview) {
    return <Toast toast={toast} />;
  }

  const pending = overview.users.filter((user) => !user.governed).length;

  return (
    <div className="flex flex-col gap-5">
      <PluginSlot name="governance:top" />
      <Toast toast={toast} />
      <header className="flex flex-col gap-4 border-b border-border pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <H2 variant="sm" className="flex items-center gap-2 text-foreground">
              <Shield className="h-4 w-4" />
              Governance
            </H2>
            <Badge tone={overview.enabled ? "success" : "destructive"}>
              {overview.enabled ? "Enabled" : "Disabled"}
            </Badge>
            {pending > 0 && <Badge tone="warning">{pending} pending users</Badge>}
          </div>
          <p className="mt-2 max-w-3xl text-sm normal-case leading-6 text-muted-foreground">
            Decide who can use Maia, which files they may read or change, and which writes require human approval.
          </p>
        </div>
        <div className="text-xs normal-case text-muted-foreground">
          Tenant <code>{overview.tenant_id}</code> · {overview.users.length} identities
        </div>
      </header>

      <nav aria-label="Governance sections" className="flex overflow-x-auto border-b border-border">
        {SECTIONS.map((item) => {
          const meta = SECTION_META[item];
          const Icon = meta.icon;
          return (
            <button
              key={item}
              type="button"
              onClick={() => selectSection(item)}
              className={cn(
                "flex min-w-max items-center gap-2 border-b-2 px-4 py-3 text-sm normal-case transition-colors",
                section === item
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
              title={meta.description}
            >
              <Icon className="h-4 w-4" />
              {meta.label}
            </button>
          );
        })}
      </nav>

      {section === "people" && <PeopleWorkspace overview={overview} reload={load} />}
      {section === "files" && <FileAccessPage embedded />}
      {section === "approvals" && <FileApprovalsPage embedded />}
      {section === "settings" && <SettingsWorkspace overview={overview} reload={load} />}
      <PluginSlot name="governance:bottom" />
    </div>
  );
}
