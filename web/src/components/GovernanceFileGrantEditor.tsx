import { useCallback, useState } from "react";
import { FolderOpen, Plus, Trash2 } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { GovernancePathPicker } from "@/components/GovernancePathPicker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { GovernanceFileGrant } from "@/lib/api";

export function GovernanceFileGrantEditor({
  grants,
  onChange,
  approvalRoles = [],
  approvalUsers = [],
  title = "Direct file and folder access",
  description = "Grant only the paths required for this identity's work.",
  disabled = false,
}: {
  grants: GovernanceFileGrant[];
  onChange: (grants: GovernanceFileGrant[]) => void;
  approvalRoles?: string[];
  approvalUsers?: Array<{ actor_key: string; name: string; roles?: string[] }>;
  title?: string;
  description?: string;
  disabled?: boolean;
}) {
  const [browseIndex, setBrowseIndex] = useState<number | null>(null);
  const closeBrowser = useCallback(() => setBrowseIndex(null), []);

  const add = () =>
    onChange([
      ...grants,
      { path: "", recursive: true, read: true, write: false },
    ]);

  const update = (index: number, patch: Partial<GovernanceFileGrant>) =>
    onChange(
      grants.map((grant, position) =>
        position === index ? { ...grant, ...patch } : grant,
      ),
    );

  const remove = (index: number) =>
    onChange(grants.filter((_, position) => position !== index));

  const setWriteMode = (
    index: number,
    grant: GovernanceFileGrant,
    mode: "none" | "direct" | "approval",
  ) => {
    if (mode === "none") {
      const next = { ...grant, write: false };
      delete next.write_approval_roles;
      delete next.write_approval_users;
      update(index, { ...next, read: true });
      return;
    }
    if (mode === "direct") {
      update(index, {
        write: true,
        write_approval_roles: [],
        write_approval_users: [],
      });
      return;
    }
    const defaultRole =
      (approvalRoles.includes("manager") && "manager") ||
      (approvalRoles.includes("admin") && "admin") ||
      approvalRoles[approvalRoles.length - 1];
    update(index, {
      write: true,
      write_approval_roles:
        (grant.write_approval_roles?.length ?? 0) > 0
          ? grant.write_approval_roles
          : defaultRole
            ? [defaultRole]
            : [],
      write_approval_users: grant.write_approval_users ?? [],
    });
  };

  const toggleApprover = (
    index: number,
    grant: GovernanceFileGrant,
    field: "write_approval_roles" | "write_approval_users",
    value: string,
  ) => {
    const current = grant[field] ?? [];
    const next = current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value];
    const other =
      field === "write_approval_roles"
        ? (grant.write_approval_users ?? [])
        : (grant.write_approval_roles ?? []);
    if (next.length === 0 && other.length === 0) return;
    update(index, { [field]: next });
  };

  return (
    <section className="space-y-3 border-t border-border pt-5 normal-case">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {description}
          </p>
        </div>
        <Button size="sm" onClick={add} disabled={disabled}>
          <Plus className="h-4 w-4" />
          Add file or folder
        </Button>
      </div>

      {grants.length === 0 ? (
        <div className="border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
          No direct paths. Access can still come from role or team policies.
        </div>
      ) : (
        <div className="space-y-3">
          {grants.map((grant, index) => {
            const approvalRequired =
              grant.write &&
              ((grant.write_approval_roles?.length ?? 0) > 0 ||
                (grant.write_approval_users?.length ?? 0) > 0);
            const writeMode = !grant.write
              ? "none"
              : approvalRequired
                ? "approval"
                : "direct";
            const selectedApprovalRoles = grant.write_approval_roles ?? [];
            const selectedApprovalUsers = grant.write_approval_users ?? [];
            const eligibleApprovalUsers = approvalUsers.filter((user) => {
              if (selectedApprovalUsers.includes(user.actor_key)) return true;
              return (user.roles ?? []).some((grantedRole) =>
                selectedApprovalRoles.some((requiredRole) => {
                  const grantedIndex = approvalRoles.indexOf(grantedRole);
                  const requiredIndex = approvalRoles.indexOf(requiredRole);
                  return grantedIndex >= 0 && requiredIndex >= 0
                    ? grantedIndex >= requiredIndex
                    : grantedRole === requiredRole;
                }),
              );
            });
            return (
              <div key={index} className="space-y-4 border border-border bg-background p-4">
                <div className="flex items-center justify-between gap-3 border-b border-border pb-3">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Path {index + 1}
                    </div>
                    <div className="mt-1 max-w-xl truncate font-mono-ui text-xs text-foreground">
                      {grant.path || "Choose a server file or folder"}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    ghost
                    destructive
                    onClick={() => remove(index)}
                    disabled={disabled}
                    aria-label={`Remove access for ${grant.path || "new path"}`}
                  >
                    <Trash2 className="h-4 w-4" />
                    Remove
                  </Button>
                </div>
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 xl:items-end">
                  <div className="grid gap-2 sm:col-span-2 xl:col-span-3">
                    <Label htmlFor={`governance-server-path-${index}`}>
                      Server path
                    </Label>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <Input
                        id={`governance-server-path-${index}`}
                        value={grant.path}
                        onChange={(event) =>
                          update(index, { path: event.target.value })
                        }
                        placeholder="/srv/company/finance or /srv/company/plan.pdf"
                        disabled={disabled}
                      />
                      <Button
                        size="sm"
                        outlined
                        className="shrink-0"
                        onClick={() => setBrowseIndex(index)}
                        disabled={disabled}
                        aria-label={`Browse server files for ${grant.path || "new path"}`}
                      >
                        <FolderOpen className="h-4 w-4" />
                        Browse
                      </Button>
                    </div>
                  </div>
                  <GrantToggle
                    label="Read"
                    checked={grant.read}
                    disabled={disabled}
                    onChange={(read) => {
                      if (!read && !grant.write) return;
                      update(index, { read });
                    }}
                  />
                  <label className="grid gap-2 text-xs text-muted-foreground">
                    Write access
                    <select
                      value={writeMode}
                      onChange={(event) =>
                        setWriteMode(
                          index,
                          grant,
                          event.target.value as "none" | "direct" | "approval",
                        )
                      }
                      disabled={disabled}
                      className="h-10 border border-border bg-background px-3 text-sm text-foreground"
                    >
                      <option value="none">No write</option>
                      <option value="direct">Direct write</option>
                      <option value="approval">Write after approval</option>
                    </select>
                  </label>
                  <GrantToggle
                    label="Include children"
                    checked={grant.recursive}
                    disabled={disabled}
                    onChange={(recursive) => update(index, { recursive })}
                  />
                </div>

                {writeMode === "approval" && (
                  <div className="grid gap-4 border border-border bg-muted/20 p-4 lg:grid-cols-2">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Approver roles
                      </div>
                      <div className="mt-3 flex flex-wrap gap-3">
                        {approvalRoles.map((role) => (
                          <ApprovalToggle
                            key={role}
                            label={role}
                            checked={(
                              grant.write_approval_roles ?? []
                            ).includes(role)}
                            disabled={disabled}
                            onChange={() =>
                              toggleApprover(
                                index,
                                grant,
                                "write_approval_roles",
                                role,
                              )
                            }
                          />
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Specific approvers
                      </div>
                      <div className="mt-3 grid max-h-32 gap-2 overflow-y-auto sm:grid-cols-2">
                        {approvalUsers.map((user) => (
                          <ApprovalToggle
                            key={user.actor_key}
                            label={user.name || user.actor_key}
                            checked={(
                              grant.write_approval_users ?? []
                            ).includes(user.actor_key)}
                            disabled={disabled}
                            onChange={() =>
                              toggleApprover(
                                index,
                                grant,
                                "write_approval_users",
                                user.actor_key,
                              )
                            }
                          />
                        ))}
                        {approvalUsers.length === 0 && (
                          <span className="text-xs text-muted-foreground">
                            Add another governed identity to choose a specific
                            approver.
                          </span>
                        )}
                      </div>
                    </div>
                    {eligibleApprovalUsers.length === 0 && (
                      <div className="border border-red-500/40 bg-red-500/5 p-3 text-xs leading-5 text-red-600 lg:col-span-2 dark:text-red-400">
                        No governed gateway identity currently satisfies this
                        approval selection. Assign the selected role to a user
                        or choose a specific approver before saving.
                      </div>
                    )}
                    <p className="text-xs leading-5 text-muted-foreground lg:col-span-2">
                      This approval checkpoint belongs to the matching path
                      policy. It applies to every non-approver who can write
                      this same path. Selecting a role makes every governed
                      identity at that role or higher eligible; choosing a
                      specific approver is optional. At least one actual
                      identity must qualify. Raw terminal and code writes
                      remain read-only so they cannot bypass review.
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {browseIndex !== null && grants[browseIndex] && (
        <GovernancePathPicker
          initialPath={grants[browseIndex].path}
          onClose={closeBrowser}
          onSelect={(path) => update(browseIndex, { path })}
        />
      )}
    </section>
  );
}

function ApprovalToggle({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: () => void;
  disabled: boolean;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-foreground">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
      />
      <span className="truncate">{label}</span>
    </label>
  );
}

function GrantToggle({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled: boolean;
}) {
  return (
    <label className="flex min-h-10 items-center gap-2 text-xs text-muted-foreground">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
      />
      {label}
    </label>
  );
}
