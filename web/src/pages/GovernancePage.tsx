import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  FileCheck,
  FolderTree,
  Network,
  Plus,
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
import { RoleMultiSelect, TeamMultiSelect } from "@/components/GovernanceFields";
import { GovernanceFileGrantEditor } from "@/components/GovernanceFileGrantEditor";
import { H2 } from "@/components/NouiTypography";
import { SecureRuntimePanel } from "@/components/SecureRuntimePanel";
import { Toast } from "@/components/Toast";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/useToast";
import {
  api,
  type GovernanceFileGrant,
  type GovernanceOverview,
  type GovernanceSandboxStatus,
  type GovernanceTeam,
  type GovernanceUser,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { PluginSlot } from "@/plugins";
import FileAccessPage from "@/pages/FileAccessPage";
import FileApprovalsPage from "@/pages/FileApprovalsPage";

const SECTIONS = ["people", "teams", "files", "approvals", "settings"] as const;
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
  teams: {
    label: "Teams",
    icon: Network,
    description: "Create teams, assign people, delegate roots, and grant paths.",
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

type UserDraft = {
  name: string;
  roles: string[];
  teams: string[];
  file_access: GovernanceFileGrant[];
};

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
  const [gatewayHelpOpen, setGatewayHelpOpen] = useState(false);
  const [draft, setDraft] = useState<UserDraft>({
    name: "",
    roles: [],
    teams: [],
    file_access: [],
  });
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
      teams: selected.teams,
      file_access: selected.file_access.map((grant) => ({ ...grant })),
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
        teams: draft.teams,
        file_access: draft.file_access,
      });
      showToast(
        `${selected.actor_key} is active. File access applies on the user's next request; no new thread or gateway restart is required.`,
        "success",
      );
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
          <div className="flex items-center gap-2">
            <Link
              to="/gateway"
              className="group relative inline-flex min-h-8 flex-1 items-center justify-center gap-2 bg-midground px-3 py-1.5 font-mono-ui text-[0.7rem] font-bold uppercase tracking-[0.15em] text-background-base shadow-[inset_-1px_-1px_0_0_#00000080,inset_1px_1px_0_0_#ffffff80] transition-opacity hover:opacity-90"
            >
              <Plus className="h-3.5 w-3.5" />
              Add user on Gateway
            </Link>
            <button
              type="button"
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border text-xs font-bold text-muted-foreground hover:border-primary hover:text-primary"
              aria-label="Why users are added from Gateway"
              aria-expanded={gatewayHelpOpen}
              title="Users must be admitted by a messaging platform before Governance can assign their access."
              onClick={() => setGatewayHelpOpen((open) => !open)}
            >
              ?
            </button>
          </div>
          {gatewayHelpOpen && (
            <div
              role="tooltip"
              className="border border-border/60 bg-muted/30 p-3 text-xs normal-case leading-5 text-muted-foreground"
            >
              This opens Gateway, where you add the person&apos;s Slack, Discord, Mattermost, or Matrix ID first.
              Return here afterward to grant their role, team membership, and file access.
            </div>
          )}
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
                <div className="flex items-center justify-between gap-3">
                  <Label>Teams</Label>
                  <Link
                    to="/governance?section=teams"
                    className="text-xs font-semibold text-primary hover:underline"
                  >
                    Manage teams
                  </Link>
                </div>
                <TeamMultiSelect
                  value={draft.teams}
                  onChange={(teams) => setDraft((current) => ({ ...current, teams }))}
                  options={overview.teams}
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

            <GovernanceFileGrantEditor
              grants={draft.file_access}
              onChange={(file_access) =>
                setDraft((current) => ({ ...current, file_access }))
              }
              approvalRoles={overview.role_hierarchy}
              approvalUsers={overview.users.filter(
                (user) => user.governed && user.actor_key !== selected.actor_key,
              )}
              description="These grants apply only to this identity and merge with team and role policies for the same path."
            />

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

type TeamDraft = {
  members: string[];
  file_access: GovernanceFileGrant[];
  delegated_root: GovernanceTeam["delegated_root"];
};

function TeamsWorkspace({
  overview,
  reload,
}: {
  overview: GovernanceOverview;
  reload: () => Promise<void>;
}) {
  const [params, setParams] = useSearchParams();
  const requestedTeam = params.get("team") ?? "";
  const [query, setQuery] = useState("");
  const [selectedName, setSelectedName] = useState(requestedTeam);
  const [newTeamName, setNewTeamName] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<TeamDraft>({
    members: [],
    file_access: [],
    delegated_root: null,
  });
  const { toast, showToast } = useToast();

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return overview.team_records.filter((team) =>
      !needle
        ? true
        : [team.name, ...team.members, ...(team.file_access.map((grant) => grant.path))]
            .join(" ")
            .toLowerCase()
            .includes(needle),
    );
  }, [overview.team_records, query]);

  const selected =
    overview.team_records.find((team) => team.name === selectedName) ??
    filtered[0] ??
    null;

  useEffect(() => {
    if (!selected) return;
    // Keep the inspector aligned with the selected team after reloads.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft({
      members: [...selected.members],
      file_access: selected.file_access.map((grant) => ({ ...grant })),
      delegated_root: selected.delegated_root
        ? {
            ...selected.delegated_root,
            manager_roles: [...(selected.delegated_root.manager_roles ?? [])],
            managers: [...(selected.delegated_root.managers ?? [])],
          }
        : null,
    });
  }, [selected]);

  const selectTeam = (name: string) => {
    setSelectedName(name);
    const next = new URLSearchParams(params);
    next.set("section", "teams");
    next.set("team", name);
    next.delete("user");
    setParams(next, { replace: true });
  };

  const create = async () => {
    const name = newTeamName.trim();
    if (!name) {
      showToast("Enter a team name.", "error");
      return;
    }
    setBusy(true);
    try {
      await api.createGovernanceTeam(name);
      showToast(`${name} created.`, "success");
      setNewTeamName("");
      setSelectedName(name);
      const next = new URLSearchParams(params);
      next.set("section", "teams");
      next.set("team", name);
      setParams(next, { replace: true });
      await reload();
    } catch (error) {
      showToast(`Could not create team: ${error}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await api.saveGovernanceTeam(selected.name, draft);
      showToast(
        `${selected.name} saved. File access applies on the user's next request; no new thread or gateway restart is required.`,
        "success",
      );
      await reload();
    } catch (error) {
      showToast(`Could not save team: ${error}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!selected) return;
    if (!window.confirm(`Delete team ${selected.name}? The team must be empty first.`)) {
      return;
    }
    setBusy(true);
    try {
      await api.removeGovernanceTeam(selected.name);
      showToast(`${selected.name} deleted.`, "success");
      setSelectedName("");
      await reload();
    } catch (error) {
      showToast(`Could not delete team: ${error}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const toggleMember = (actorKey: string) =>
    setDraft((current) => ({
      ...current,
      members: current.members.includes(actorKey)
        ? current.members.filter((key) => key !== actorKey)
        : [...current.members, actorKey],
    }));

  const toggleRootManager = (actorKey: string) =>
    setDraft((current) => {
      if (!current.delegated_root) return current;
      const managers = current.delegated_root.managers ?? [];
      return {
        ...current,
        delegated_root: {
          ...current.delegated_root,
          managers: managers.includes(actorKey)
            ? managers.filter((key) => key !== actorKey)
            : [...managers, actorKey],
        },
      };
    });

  const governedUsers = overview.users.filter((user) => user.governed);

  return (
    <div className="grid min-h-[36rem] gap-0 border border-border lg:grid-cols-[minmax(18rem,0.8fr)_minmax(28rem,1.6fr)]">
      <Toast toast={toast} />
      <section className="border-b border-border bg-muted/10 lg:border-b-0 lg:border-r">
        <div className="space-y-3 border-b border-border p-4">
          <div>
            <div className="text-sm font-semibold normal-case">Teams</div>
            <div className="text-xs normal-case text-muted-foreground">
              {overview.team_records.length} registered
            </div>
          </div>
          <div className="flex gap-2">
            <Input
              value={newTeamName}
              onChange={(event) => setNewTeamName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void create();
              }}
              placeholder="New team name"
              aria-label="New team name"
            />
            <Button size="sm" onClick={create} disabled={busy}>
              <Plus className="h-4 w-4" />
              Create
            </Button>
          </div>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search teams, people, or paths"
              className="pl-8"
            />
          </div>
        </div>
        <div className="max-h-[54rem] overflow-y-auto">
          {filtered.map((team) => (
            <button
              key={team.name}
              type="button"
              onClick={() => selectTeam(team.name)}
              className={cn(
                "grid w-full gap-1 border-b border-border/70 px-4 py-3 text-left normal-case transition-colors",
                selected?.name === team.name ? "bg-primary/10" : "hover:bg-muted/30",
              )}
            >
              <span className="text-sm font-medium text-foreground">{team.name}</span>
              <span className="text-xs text-muted-foreground">
                {team.members.length} people · {team.file_access.length} paths
                {team.delegated_root ? " · delegated root" : ""}
              </span>
            </button>
          ))}
          {filtered.length === 0 && (
            <div className="p-6 text-center text-sm normal-case text-muted-foreground">
              No teams yet. Create one above.
            </div>
          )}
        </div>
      </section>

      <section className="min-w-0 p-5 lg:p-6">
        {selected ? (
          <div className="space-y-6">
            <div className="flex flex-col gap-3 border-b border-border pb-5 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <H2 variant="sm" className="normal-case text-foreground">{selected.name}</H2>
                <p className="mt-1 text-xs normal-case text-muted-foreground">
                  Membership and grants are saved together.
                </p>
              </div>
              <div className="flex gap-2">
                <Button size="sm" ghost onClick={remove} disabled={busy}>
                  <Trash2 className="h-4 w-4" />
                  Delete team
                </Button>
                <Button size="sm" onClick={save} disabled={busy}>
                  {busy ? <Spinner className="h-4 w-4" /> : <Save className="h-4 w-4" />}
                  Save team
                </Button>
              </div>
            </div>

            <section className="space-y-3 normal-case">
              <div>
                <h3 className="text-sm font-semibold">People</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Only identities already granted a Governance role can join a team.
                </p>
              </div>
              <div className="grid divide-y divide-border border border-border sm:grid-cols-2 sm:divide-x sm:divide-y-0">
                {governedUsers.map((user) => (
                  <label key={user.actor_key} className="flex items-start gap-3 p-3 text-sm">
                    <input
                      type="checkbox"
                      checked={draft.members.includes(user.actor_key)}
                      onChange={() => toggleMember(user.actor_key)}
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{user.name || user.actor_key}</span>
                      <span className="block truncate font-mono-ui text-[0.7rem] text-muted-foreground">
                        {user.actor_key}
                      </span>
                    </span>
                  </label>
                ))}
                {governedUsers.length === 0 && (
                  <div className="p-4 text-sm text-muted-foreground">Grant a person a role first.</div>
                )}
              </div>
            </section>

            <GovernanceFileGrantEditor
              grants={draft.file_access}
              onChange={(file_access) => setDraft((current) => ({ ...current, file_access }))}
              approvalRoles={overview.role_hierarchy}
              approvalUsers={overview.users.filter((user) => user.governed)}
              title="Team file and folder access"
              description="These read/write grants apply to every governed member of this team."
            />

            <section className="space-y-4 border-t border-border pt-5 normal-case">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold">Delegated management root</h3>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    Optional boundary below which authorized team managers may edit advanced policies.
                  </p>
                </div>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={Boolean(draft.delegated_root)}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        delegated_root: event.target.checked
                          ? { path: "", manager_roles: ["manager"], managers: [] }
                          : null,
                      }))
                    }
                  />
                  Enable
                </label>
              </div>
              {draft.delegated_root && (
                <div className="grid gap-5 border border-border p-4 lg:grid-cols-2">
                  <label className="grid gap-2 lg:col-span-2">
                    <Label>Server root</Label>
                    <Input
                      value={draft.delegated_root.path}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          delegated_root: current.delegated_root
                            ? { ...current.delegated_root, path: event.target.value }
                            : null,
                        }))
                      }
                      placeholder="/srv/company/marketing"
                    />
                  </label>
                  <div className="grid gap-2">
                    <Label>Manager roles</Label>
                    <RoleMultiSelect
                      value={draft.delegated_root.manager_roles ?? []}
                      onChange={(manager_roles) =>
                        setDraft((current) => ({
                          ...current,
                          delegated_root: current.delegated_root
                            ? { ...current.delegated_root, manager_roles }
                            : null,
                        }))
                      }
                      options={overview.role_hierarchy}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label>Named managers</Label>
                    <div className="max-h-36 overflow-y-auto border border-border">
                      {governedUsers.map((user) => (
                        <label key={user.actor_key} className="flex items-center gap-2 border-b border-border/70 px-3 py-2 text-xs last:border-b-0">
                          <input
                            type="checkbox"
                            checked={(draft.delegated_root?.managers ?? []).includes(user.actor_key)}
                            onChange={() => toggleRootManager(user.actor_key)}
                          />
                          <span className="truncate">{user.name || user.actor_key}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </section>
          </div>
        ) : (
          <div className="flex min-h-80 items-center justify-center text-sm normal-case text-muted-foreground">
            Create a team to assign people and file access.
          </div>
        )}
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
        tenant_id: draft.tenant_id,
        default_role: draft.default_role,
        role_hierarchy: draft.role_hierarchy,
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
            <div className="border border-emerald-500/30 bg-emerald-500/5 p-3">
              <span>
                <span className="block text-sm font-medium">Governance is always enforced</span>
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                  Human gateway users fail closed. Roles admit a person to the bot; only explicit policies grant file or folder access.
                </span>
              </span>
            </div>
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
          <CardHeader><CardTitle>Team delegation</CardTitle></CardHeader>
          <CardContent className="grid gap-5">
            {roleSetting(
              "Roles that may manage delegated team roots",
              draft.team_file_manager_roles,
              (roles) => setDraft((current) => ({ ...current, team_file_manager_roles: roles })),
              "Configure each root in Governance / Teams. These users remain limited to the root delegated to their team.",
            )}
            <p className="text-xs normal-case leading-5 text-muted-foreground">
              File access is always deny-by-default. There is no global allow mode;
              every readable or writable path needs an explicit policy.
            </p>
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
  const [sandboxStatus, setSandboxStatus] = useState<GovernanceSandboxStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const { toast, showToast } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextOverview, nextSandboxStatus] = await Promise.all([
        api.getGovernanceOverview(),
        api.getSecureRuntimeStatus().catch(() => null),
      ]);
      setOverview(nextOverview);
      setSandboxStatus(nextSandboxStatus);
    } catch (error) {
      showToast(`Failed to load Governance: ${error}`, "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  const finishRuntimeSetup = useCallback(async () => {
    setLoading(true);
    try {
      const nextStatus = await api.provisionSecureRuntime();
      setSandboxStatus(nextStatus);
      showToast("Secure runtime is ready", "success");
    } catch (error) {
      showToast(`Could not finish secure runtime setup: ${error}`, "error");
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
    if (nextSection !== "teams") next.delete("team");
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
            {sandboxStatus && (
              <Badge tone={sandboxStatus.ready ? "success" : "warning"}>
                {sandboxStatus.ready ? "Full automation" : "Restricted mode"}
              </Badge>
            )}
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

      {sandboxStatus && (
        <SecureRuntimePanel
          status={sandboxStatus}
          loading={loading}
          onSetup={() => void finishRuntimeSetup()}
          onRefresh={() => void load()}
        />
      )}

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
      {section === "teams" && <TeamsWorkspace overview={overview} reload={load} />}
      {section === "files" && <FileAccessPage embedded />}
      {section === "approvals" && <FileApprovalsPage embedded />}
      {section === "settings" && <SettingsWorkspace overview={overview} reload={load} />}
      <PluginSlot name="governance:bottom" />
    </div>
  );
}
