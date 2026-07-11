import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { FolderTree, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import {
  HelpBox,
  HelpDot,
  RoleMultiSelect,
  TeamsHelpContent,
  useGovernanceOptions,
} from "@/components/GovernanceFields";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/NouiTypography";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toast } from "@/components/Toast";
import { api, type FolderPoliciesResponse, type FolderPolicy } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { PluginSlot } from "@/plugins";

function listToText(value?: string[]): string {
  return (value ?? []).join(", ");
}

function textToList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function valueToText(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(", ");
  }
  if (typeof value === "string") {
    return value;
  }
  return "";
}

function updateListField(
  policy: FolderPolicy,
  key: keyof FolderPolicy,
  value: string,
): FolderPolicy {
  const next = { ...policy };
  const values = textToList(value);
  if (values.length) {
    (next as Record<string, unknown>)[key] = values;
  } else {
    delete (next as Record<string, unknown>)[key];
  }
  return next;
}

type TeamRootDraft = {
  team: string;
  path: string;
  manager_roles: string;
  managers: string;
};

function teamRootsToDrafts(
  roots: FolderPoliciesResponse["team_file_roots"],
): TeamRootDraft[] {
  return Object.entries(roots ?? {}).map(([team, entry]) => ({
    team,
    path: String(entry.path ?? ""),
    manager_roles: valueToText(entry.manager_roles),
    managers: valueToText(entry.managers ?? entry.manager_users),
  }));
}

function teamRootDraftsToConfig(
  drafts: TeamRootDraft[],
): Record<string, Record<string, unknown>> {
  const result: Record<string, Record<string, unknown>> = {};
  for (const draft of drafts) {
    const team = draft.team.trim();
    const path = draft.path.trim();
    if (!team && !path) continue;
    if (!team || !path) {
      throw new Error("Each delegated team root needs both a team and a server path.");
    }
    const entry: Record<string, unknown> = { path };
    const managerRoles = textToList(draft.manager_roles);
    const managers = textToList(draft.managers);
    if (managerRoles.length) entry.manager_roles = managerRoles;
    if (managers.length) entry.managers = managers;
    result[team] = entry;
  }
  return result;
}

export default function FileAccessPage({ embedded = false }: { embedded?: boolean }) {
  const [data, setData] = useState<FolderPoliciesResponse | null>(null);
  const [policies, setPolicies] = useState<FolderPolicy[]>([]);
  const [teamRoots, setTeamRoots] = useState<TeamRootDraft[]>([]);
  const [defaultFilePolicy, setDefaultFilePolicy] = useState("deny");
  const [selectedPolicyIndex, setSelectedPolicyIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { toast, showToast } = useToast();
  const { roles: roleOptions, teams: teamOptions } = useGovernanceOptions();

  const teamsHelp = <TeamsHelpContent existingTeams={teamOptions} />;
  const actorKeyHelp = (
    <>
      Exact actor keys in the <code>&lt;platform&gt;:&lt;user id&gt;</code>{" "}
      format, e.g. <code>slack:U01ABC2DEF3</code> or{" "}
      <code>discord:99887766</code>. Copy them from each platform&apos;s users
      editor in{" "}
      <Link to="/gateway" className="font-bold text-primary hover:underline">
        Gateway
      </Link>{" "}
      or from{" "}
      <Link to="/dashboard-access" className="font-bold text-primary hover:underline">
        Access
      </Link>
      .
    </>
  );
  const serverPathHelp = (
    <>
      A path on the machine running Maia, e.g.{" "}
      <code>/srv/company/marketing</code> or <code>/home/maia/company-files</code>.
      The directory must exist and be readable by the Maia process; on WSL
      keep governed folders on the Linux filesystem.
    </>
  );

  const load = useCallback(() => {
    setLoading(true);
    api
      .getFolderPolicies()
      .then((resp) => {
        setData(resp);
        setPolicies(resp.folder_policies);
        setSelectedPolicyIndex((current) =>
          resp.folder_policies.length === 0
            ? 0
            : Math.min(current, resp.folder_policies.length - 1),
        );
        setTeamRoots(teamRootsToDrafts(resp.team_file_roots));
        setDefaultFilePolicy(resp.default_file_policy || "deny");
      })
      .catch((err) => showToast(`Failed to load file access: ${err}`, "error"))
      .finally(() => setLoading(false));
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  const updatePolicy = (index: number, next: FolderPolicy) => {
    setPolicies((current) =>
      current.map((policy, idx) => (idx === index ? next : policy)),
    );
  };

  const addPolicy = () => {
    const firstTeam = data?.actor.managed_teams[0];
    const root = firstTeam ? data?.team_file_roots[firstTeam]?.path : "";
    setSelectedPolicyIndex(policies.length);
    setPolicies((current) => [
      ...current,
      {
        path: root || "",
        recursive: true,
        read_teams: firstTeam ? [firstTeam] : [],
      },
    ]);
  };

  const removePolicy = (index: number) => {
    setPolicies((current) => current.filter((_, idx) => idx !== index));
    setSelectedPolicyIndex((current) => {
      const nextLength = Math.max(0, policies.length - 1);
      if (nextLength === 0) return 0;
      if (current > index) return current - 1;
      return Math.min(current, nextLength - 1);
    });
  };

  const updateTeamRoot = (index: number, patch: Partial<TeamRootDraft>) => {
    setTeamRoots((current) =>
      current.map((root, idx) => (idx === index ? { ...root, ...patch } : root)),
    );
  };

  const addTeamRoot = () => {
    setTeamRoots((current) => [
      ...current,
      { team: "", path: "", manager_roles: "manager", managers: "" },
    ]);
  };

  const removeTeamRoot = (index: number) => {
    setTeamRoots((current) => current.filter((_, idx) => idx !== index));
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.saveFolderPolicies({
        default_file_policy: data?.actor.can_admin ? defaultFilePolicy : undefined,
        folder_policies: policies,
        team_file_roots: data?.actor.can_admin
          ? teamRootDraftsToConfig(teamRoots)
          : undefined,
      });
      showToast("File access policies saved", "success");
      load();
    } catch (err) {
      showToast(`Failed to save policies: ${err}`, "error");
    } finally {
      setSaving(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner className="text-2xl text-primary" />
      </div>
    );
  }

  const canAdmin = Boolean(data?.actor.can_admin);

  return (
    <div className="flex flex-col gap-6">
      {!embedded && <PluginSlot name="file-access:top" />}
      <Toast toast={toast} />

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={data?.enabled ? "success" : "destructive"}>
            Governance {data?.enabled ? "enabled" : "disabled"}
          </Badge>
          <Badge tone={canAdmin ? "warning" : "secondary"}>
            {canAdmin ? "System admin" : "Team manager"}
          </Badge>
          {(data?.actor.managed_teams ?? []).map((team) => (
            <Badge key={team} tone="outline">
              {team}
            </Badge>
          ))}
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          {!embedded && (
            <H2 variant="sm" className="flex items-center gap-2 text-muted-foreground">
              <FolderTree className="h-4 w-4" />
              File Access
            </H2>
          )}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={load} disabled={loading}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
            <Button size="sm" onClick={addPolicy}>
              <Plus className="h-4 w-4" />
              Add policy
            </Button>
            <Button size="sm" onClick={save} disabled={saving}>
              <Save className="h-4 w-4" />
              Save
            </Button>
          </div>
        </div>
        <p className="max-w-3xl text-sm normal-case leading-6 text-muted-foreground">
          File policies are the server-side maximum for file reads, searches,
          writes, and patches. System admins can edit global policy and role-wide
          grants. Team managers can save only policies under delegated team roots
          and only for users or teams they manage.
        </p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Authorization setup order</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 normal-case text-sm leading-6 text-muted-foreground md:grid-cols-3">
          <div>
            <span className="font-medium text-foreground">1. Provision identities</span>
            <p>Admins grant each platform:user_id roles and teams in Governance / People before the user can access the bot.</p>
          </div>
          <div>
            <span className="font-medium text-foreground">2. Delegate roots</span>
            <p>Admins add team roots here when team managers should control a bounded server folder.</p>
          </div>
          <div>
            <span className="font-medium text-foreground">3. Grant access</span>
            <p>Use read/write teams for groups and read/write users for exact actor keys.</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Scope</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 normal-case md:grid-cols-2">
          <div className="space-y-2">
            <Label>Default file policy</Label>
            <select
              value={defaultFilePolicy}
              onChange={(event) => setDefaultFilePolicy(event.target.value)}
              disabled={!canAdmin}
              className="h-10 w-full border border-border bg-background px-3 text-sm"
            >
              <option value="deny">deny</option>
              <option value="allow">allow</option>
            </select>
            <p className="text-xs leading-5 text-muted-foreground">
              Use deny in production. This decides what happens when no folder
              policy matches a path. Team managers cannot change the global default.
            </p>
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label>Delegated team roots</Label>
              {canAdmin && (
                <Button size="sm" onClick={addTeamRoot}>
                  <Plus className="h-4 w-4" />
                  Add root
                </Button>
              )}
            </div>
            {canAdmin ? (
              <div className="space-y-3">
                {teamRoots.map((root, index) => (
                  <div
                    key={`${root.team}-${index}`}
                    className="grid gap-3 border border-border p-3 md:grid-cols-2"
                  >
                    <Field
                      label="Team"
                      value={root.team}
                      onChange={(value) => updateTeamRoot(index, { team: value })}
                      placeholder="marketing"
                      list="fileaccess-team-options"
                      help={teamsHelp}
                      note=""
                    />
                    <Field
                      label="Server root"
                      value={root.path}
                      onChange={(value) => updateTeamRoot(index, { path: value })}
                      placeholder="/srv/company/marketing"
                      help={serverPathHelp}
                      note=""
                    />
                    <div className="space-y-2">
                      <Label>Manager roles</Label>
                      <RoleMultiSelect
                        value={textToList(root.manager_roles)}
                        onChange={(roles) =>
                          updateTeamRoot(index, { manager_roles: roles.join(", ") })
                        }
                        options={roleOptions}
                        emptyHint="who may manage this root"
                      />
                    </div>
                    <div className="flex gap-2">
                      <div className="flex-1">
                        <Field
                          label="Manager users"
                          value={root.managers}
                          onChange={(value) =>
                            updateTeamRoot(index, { managers: value })
                          }
                          placeholder="sso:ana@company.com"
                          help={actorKeyHelp}
                        />
                      </div>
                      <Button
                        size="icon"
                        ghost
                        onClick={() => removeTeamRoot(index)}
                        className="mt-7"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                ))}
                {teamRoots.length === 0 && (
                  <p className="text-xs leading-5 text-muted-foreground">
                    No team roots configured. Add a root to let a team manager
                    administer a bounded server folder.
                  </p>
                )}
              </div>
            ) : (
              <div className="space-y-1 text-xs leading-5 text-muted-foreground">
                {Object.entries(data?.team_file_roots ?? {}).map(([team, entry]) => (
                  <div key={team} className="truncate">
                    <span className="text-foreground">{team}:</span> {String(entry.path)}
                  </div>
                ))}
                {Object.keys(data?.team_file_roots ?? {}).length === 0 && (
                  <div>No team roots delegated to this dashboard user.</div>
                )}
              </div>
            )}
            <p className="text-xs leading-5 text-muted-foreground">
              Team managers can add or edit policies only below these server paths.
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <aside className="border border-border bg-muted/10">
          <div className="border-b border-border px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Governed paths
          </div>
          {policies.map((policy, index) => (
            <button
              key={`policy-nav-${policy.path}-${index}`}
              type="button"
              onClick={() => setSelectedPolicyIndex(index)}
              className={cn(
                "grid w-full gap-1 border-b border-border/70 px-3 py-3 text-left normal-case transition-colors",
                selectedPolicyIndex === index ? "bg-primary/10" : "hover:bg-muted/30",
              )}
            >
              <span className="break-all font-mono-ui text-xs text-foreground">
                {policy.path || "New policy"}
              </span>
              <span className="text-[0.7rem] text-muted-foreground">
                {(policy.read_roles?.length ?? 0) + (policy.read_teams?.length ?? 0) + (policy.read_users?.length ?? 0)} read grants ·{" "}
                {(policy.write_roles?.length ?? 0) + (policy.write_teams?.length ?? 0) + (policy.write_users?.length ?? 0)} write grants
                {(policy.write_approval_roles?.length ?? 0) + (policy.write_approval_users?.length ?? 0) > 0 ? " · approval required" : ""}
              </span>
            </button>
          ))}
          {policies.length === 0 && (
            <div className="p-4 text-xs normal-case leading-5 text-muted-foreground">
              No paths configured. Add a policy to grant narrow file access.
            </div>
          )}
        </aside>
        <div className="min-w-0">
        {policies.map((policy, index) => (
          selectedPolicyIndex === index ? <Card key={`${policy.path}-${index}`}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate">{policy.path || "New policy"}</span>
                <Button size="icon" ghost onClick={() => removePolicy(index)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 normal-case lg:grid-cols-2">
              <div className="lg:col-span-2">
                <Field
                  label="Server path"
                  value={policy.path}
                  onChange={(value) => updatePolicy(index, { ...policy, path: value })}
                  placeholder="/srv/company/marketing"
                  help={serverPathHelp}
                  note=""
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                <input
                  type="checkbox"
                  checked={policy.recursive !== false}
                  onChange={(event) =>
                    updatePolicy(index, { ...policy, recursive: event.target.checked })
                  }
                />
                Recursive directory policy
              </label>

              {canAdmin && (
                <div className="lg:col-span-2">
                  <RoleAccessMatrix
                    roles={roleOptions}
                    readRoles={policy.read_roles ?? []}
                    writeRoles={policy.write_roles ?? []}
                    approvalRoles={policy.write_approval_roles ?? []}
                    onChange={(key, roles) =>
                      updatePolicy(index, { ...policy, [key]: roles })
                    }
                  />
                </div>
              )}

              <Field
                label="Read teams"
                value={listToText(policy.read_teams)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "read_teams", value))}
                placeholder="marketing"
                list="fileaccess-team-options"
                help={teamsHelp}
              />
              <Field
                label="Write teams"
                value={listToText(policy.write_teams)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "write_teams", value))}
                placeholder="marketing-leads"
                list="fileaccess-team-options"
              />
              <Field
                label="Read users"
                value={listToText(policy.read_users)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "read_users", value))}
                placeholder="slack:U123, slack:U456"
                help={actorKeyHelp}
              />
              <Field
                label="Write users"
                value={listToText(policy.write_users)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "write_users", value))}
                placeholder="slack:U123"
                help={actorKeyHelp}
              />
              <Field
                label="Deny users"
                value={listToText(policy.deny_users)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "deny_users", value))}
                placeholder="discord:99887766"
                help={actorKeyHelp}
              />
              <Field
                label="Deny teams"
                value={listToText(policy.deny_teams)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "deny_teams", value))}
                placeholder="marketing"
                list="fileaccess-team-options"
              />
              <Field
                label="Write approval users"
                value={listToText(policy.write_approval_users)}
                onChange={(value) =>
                  updatePolicy(index, updateListField(policy, "write_approval_users", value))
                }
                placeholder="slack:U_MANAGER"
                help={actorKeyHelp}
              />
              <div className="space-y-2 lg:col-span-2">
                <label className="flex items-center gap-2 text-sm text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={
                      Array.isArray(policy.write_approval_roles) &&
                      policy.write_approval_roles.length === 0 &&
                      (policy.write_approval_users ?? []).length === 0
                    }
                    onChange={(event) => {
                      const next = { ...policy } as Record<string, unknown>;
                      if (event.target.checked) {
                        next.write_approval_roles = [];
                        delete next.write_approval_users;
                      } else {
                        delete next.write_approval_roles;
                      }
                      updatePolicy(index, next as FolderPolicy);
                    }}
                  />
                  Opt out of inherited write approval (saves an explicit empty list)
                </label>
                <p className="text-xs leading-5 text-muted-foreground">
                  Write approval roles/users stage every modification under this
                  policy for human review before it is applied — even for users
                  who hold a write grant. Leave both empty to inherit from a
                  parent policy; use the opt-out to cancel an inherited
                  requirement for this subtree.
                </p>
              </div>
            </CardContent>
          </Card> : null
        ))}
        </div>
      </div>

      <datalist id="fileaccess-team-options">
        {teamOptions.map((team) => (
          <option key={team} value={team} />
        ))}
      </datalist>
    </div>
  );
}

function RoleAccessMatrix({
  roles,
  readRoles,
  writeRoles,
  approvalRoles,
  onChange,
}: {
  roles: string[];
  readRoles: string[];
  writeRoles: string[];
  approvalRoles: string[];
  onChange: (
    key: "read_roles" | "write_roles" | "write_approval_roles",
    roles: string[],
  ) => void;
}) {
  const toggle = (
    key: "read_roles" | "write_roles" | "write_approval_roles",
    current: string[],
    role: string,
  ) => {
    onChange(
      key,
      current.includes(role)
        ? current.filter((item) => item !== role)
        : [...current, role],
    );
  };

  return (
    <div className="border border-border">
      <div className="border-b border-border px-3 py-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Access by role
        </div>
        <p className="mt-1 text-xs normal-case leading-5 text-muted-foreground">
          Read and write grant access to this path. Approve writes identifies who may accept staged changes;
          selecting an approver also turns on human confirmation for other writers.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] normal-case text-sm">
          <thead className="bg-muted/20 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 text-center font-medium">Read</th>
              <th className="px-3 py-2 text-center font-medium">Write</th>
              <th className="px-3 py-2 text-center font-medium">Approve writes</th>
            </tr>
          </thead>
          <tbody>
            {roles.map((role) => (
              <tr key={role} className="border-t border-border/70">
                <td className="px-3 py-2 font-mono-ui text-xs">{role}</td>
                <td className="px-3 py-2 text-center">
                  <input
                    type="checkbox"
                    aria-label={`${role} may read`}
                    checked={readRoles.includes(role)}
                    onChange={() => toggle("read_roles", readRoles, role)}
                  />
                </td>
                <td className="px-3 py-2 text-center">
                  <input
                    type="checkbox"
                    aria-label={`${role} may write`}
                    checked={writeRoles.includes(role)}
                    onChange={() => toggle("write_roles", writeRoles, role)}
                  />
                </td>
                <td className="px-3 py-2 text-center">
                  <input
                    type="checkbox"
                    aria-label={`${role} may approve writes`}
                    checked={approvalRoles.includes(role)}
                    onChange={() => toggle("write_approval_roles", approvalRoles, role)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  list,
  help,
  note = "Comma-separated.",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** Optional datalist id for value suggestions (e.g. existing teams). */
  list?: string;
  /** Optional "?"-toggled help content. */
  help?: ReactNode;
  note?: string;
}) {
  const [helpOpen, setHelpOpen] = useState(false);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5">
        <Label>{label}</Label>
        {help ? (
          <HelpDot
            ariaLabel={`Help for ${label}`}
            open={helpOpen}
            onToggle={() => setHelpOpen((open) => !open)}
          />
        ) : null}
      </div>
      <Input
        list={list}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        autoComplete="off"
      />
      {help && helpOpen ? <HelpBox>{help}</HelpBox> : null}
      {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
    </div>
  );
}
