import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { FolderTree, Plus, RefreshCw, Trash2 } from "lucide-react";
import {
  HelpBox,
  HelpDot,
  TeamMultiSelect,
} from "@/components/GovernanceFields";
import { useGovernanceOptions } from "@/hooks/useGovernanceOptions";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { H2 } from "@/components/NouiTypography";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toast } from "@/components/Toast";
import { DashboardLoadingState } from "@/components/DashboardLoadingState";
import { UnsavedChangesBar } from "@/components/UnsavedChangesBar";
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

export default function FileAccessPage({ embedded = false }: { embedded?: boolean }) {
  const [data, setData] = useState<FolderPoliciesResponse | null>(null);
  const [policies, setPolicies] = useState<FolderPolicy[]>([]);
  const [selectedPolicyIndex, setSelectedPolicyIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { toast, showToast } = useToast();
  const { roles: roleOptions, teams: teamOptions } = useGovernanceOptions();
  const isDirty = Boolean(
    data && JSON.stringify(policies) !== JSON.stringify(data.folder_policies),
  );

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
      })
      .catch((err) => showToast(`Failed to load file access: ${err}`, "error"))
      .finally(() => setLoading(false));
  }, [showToast]);

  useEffect(() => {
    // Initial remote state load.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const refresh = () => {
    if (isDirty && !window.confirm("Discard unsaved file access changes and reload?")) return;
    void load();
  };

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

  const save = async () => {
    setSaving(true);
    try {
      await api.saveFolderPolicies({
        folder_policies: policies,
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
      <div className="flex flex-col gap-5">
        {!embedded && <PluginSlot name="file-access:top" />}
        <DashboardLoadingState
          title="Restoring saved file access"
          description="Loading governed folders, role and team grants, and approval rules before showing the policy editor."
          cards={3}
        />
      </div>
    );
  }

  const canAdmin = Boolean(data?.actor.can_admin);

  return (
    <div className="flex flex-col gap-6">
      {!embedded && <PluginSlot name="file-access:top" />}
      <Toast toast={toast} />

      <div className="space-y-5 pb-20">
        <section className="border border-border bg-muted/10">
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-3">
            <div>
              <div className="text-sm font-semibold normal-case text-foreground">Policies</div>
              <div className="text-xs normal-case text-muted-foreground">{policies.length} governed paths</div>
            </div>
            <Button size="sm" onClick={addPolicy}>
              <Plus className="h-4 w-4" />
              Add policy
            </Button>
          </div>
          <div className="grid max-h-[24rem] overflow-y-auto sm:grid-cols-2 xl:grid-cols-3">
          {policies.map((policy, index) => (
            <button
              key={`policy-nav-${policy.path}-${index}`}
              type="button"
              onClick={() => setSelectedPolicyIndex(index)}
              className={cn(
                "grid w-full gap-1 border-b border-border/70 px-3 py-3 text-left normal-case transition-colors sm:border-r",
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
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-border p-3 normal-case">
            <span className="text-xs text-muted-foreground">Unmatched paths are denied.</span>
            <Button size="xs" ghost onClick={refresh} disabled={loading}>
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </Button>
          </div>
        </section>
        <section className="min-w-0 border border-border p-4 sm:p-5">
          <div className="mb-4 flex flex-col gap-3 border-b border-border pb-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              {!embedded && (
                <H2 variant="sm" className="flex items-center gap-2 text-foreground">
                  <FolderTree className="h-4 w-4" />
                  File Access
                </H2>
              )}
              <Badge tone="success">Governance enforced</Badge>
              <Badge tone={canAdmin ? "warning" : "secondary"}>
                {canAdmin ? "System admin" : "Team manager"}
              </Badge>
            </div>
          </div>
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
            <CardContent className="grid grid-cols-[minmax(0,1fr)] gap-4 normal-case xl:grid-cols-2">
              <div className="min-w-0 xl:col-span-2">
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
                <div className="min-w-0 xl:col-span-2">
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

              <div className="space-y-2">
                <Label>Read teams</Label>
                <TeamMultiSelect
                  value={policy.read_teams ?? []}
                  onChange={(read_teams) => updatePolicy(index, { ...policy, read_teams })}
                  options={teamOptions}
                />
              </div>
              <div className="space-y-2">
                <Label>Write teams</Label>
                <TeamMultiSelect
                  value={policy.write_teams ?? []}
                  onChange={(write_teams) => updatePolicy(index, { ...policy, write_teams })}
                  options={teamOptions}
                />
              </div>
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
              <div className="space-y-2">
                <Label>Deny teams</Label>
                <TeamMultiSelect
                  value={policy.deny_teams ?? []}
                  onChange={(deny_teams) => updatePolicy(index, { ...policy, deny_teams })}
                  options={teamOptions}
                />
              </div>
              <Field
                label="Write approval users"
                value={listToText(policy.write_approval_users)}
                onChange={(value) =>
                  updatePolicy(index, updateListField(policy, "write_approval_users", value))
                }
                placeholder="slack:U_MANAGER"
                help={actorKeyHelp}
              />
              <div className="space-y-2 xl:col-span-2">
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
          {policies.length === 0 && (
            <div className="flex min-h-72 items-center justify-center border border-dashed border-border text-sm normal-case text-muted-foreground">
              Add a policy to grant access to a file or folder.
            </div>
          )}
        </section>
        <UnsavedChangesBar
          dirty={isDirty}
          saving={saving}
          onSave={() => void save()}
          label="Unsaved file access policies"
          description="All policy grants and approval rules on this page will be saved together."
          saveLabel="Save policies"
        />
      </div>
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
  help,
  note = "Comma-separated.",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
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
