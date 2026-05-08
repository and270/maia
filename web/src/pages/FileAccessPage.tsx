import { useCallback, useEffect, useState } from "react";
import { FolderTree, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/NouiTypography";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toast } from "@/components/Toast";
import { api, type FolderPoliciesResponse, type FolderPolicy } from "@/lib/api";
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

export default function FileAccessPage() {
  const [data, setData] = useState<FolderPoliciesResponse | null>(null);
  const [policies, setPolicies] = useState<FolderPolicy[]>([]);
  const [teamRoots, setTeamRoots] = useState<TeamRootDraft[]>([]);
  const [defaultFilePolicy, setDefaultFilePolicy] = useState("deny");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { toast, showToast } = useToast();

  const load = useCallback(() => {
    setLoading(true);
    api
      .getFolderPolicies()
      .then((resp) => {
        setData(resp);
        setPolicies(resp.folder_policies);
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
      <PluginSlot name="file-access:top" />
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
          <H2 variant="sm" className="flex items-center gap-2 text-muted-foreground">
            <FolderTree className="h-4 w-4" />
            File Access
          </H2>
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
            <span className="font-medium text-foreground">1. Map identities</span>
            <p>Users run /whoami in their channel. Admins map those keys in Config under governance.users.</p>
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
                    />
                    <Field
                      label="Server root"
                      value={root.path}
                      onChange={(value) => updateTeamRoot(index, { path: value })}
                      placeholder="/srv/company/marketing"
                    />
                    <Field
                      label="Manager roles"
                      value={root.manager_roles}
                      onChange={(value) =>
                        updateTeamRoot(index, { manager_roles: value })
                      }
                      placeholder="manager"
                    />
                    <div className="flex gap-2">
                      <div className="flex-1">
                        <Field
                          label="Manager users"
                          value={root.managers}
                          onChange={(value) =>
                            updateTeamRoot(index, { managers: value })
                          }
                          placeholder="sso:ana@company.com"
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

      <div className="grid gap-4">
        {policies.map((policy, index) => (
          <Card key={`${policy.path}-${index}`}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate">{policy.path || "New policy"}</span>
                <Button size="icon" ghost onClick={() => removePolicy(index)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 normal-case lg:grid-cols-2">
              <div className="space-y-2 lg:col-span-2">
                <Label>Server path</Label>
                <Input
                  value={policy.path}
                  onChange={(event) =>
                    updatePolicy(index, { ...policy, path: event.target.value })
                  }
                  placeholder="/srv/company/marketing"
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

              <Field
                label="Read teams"
                value={listToText(policy.read_teams)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "read_teams", value))}
                placeholder="marketing"
              />
              <Field
                label="Write teams"
                value={listToText(policy.write_teams)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "write_teams", value))}
                placeholder="marketing-leads"
              />
              <Field
                label="Read users"
                value={listToText(policy.read_users)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "read_users", value))}
                placeholder="slack:U123, slack:U456"
              />
              <Field
                label="Write users"
                value={listToText(policy.write_users)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "write_users", value))}
                placeholder="slack:U123"
              />
              <Field
                label="Deny users"
                value={listToText(policy.deny_users)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "deny_users", value))}
                placeholder="discord:99887766"
              />
              <Field
                label="Deny teams"
                value={listToText(policy.deny_teams)}
                onChange={(value) => updatePolicy(index, updateListField(policy, "deny_teams", value))}
                placeholder="marketing"
              />
              {canAdmin && (
                <>
                  <Field
                    label="Read roles"
                    value={listToText(policy.read_roles)}
                    onChange={(value) => updatePolicy(index, updateListField(policy, "read_roles", value))}
                    placeholder="viewer, manager"
                  />
                  <Field
                    label="Write roles"
                    value={listToText(policy.write_roles)}
                    onChange={(value) => updatePolicy(index, updateListField(policy, "write_roles", value))}
                    placeholder="manager, admin"
                  />
                </>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
      <p className="text-xs text-muted-foreground">Comma-separated.</p>
    </div>
  );
}
