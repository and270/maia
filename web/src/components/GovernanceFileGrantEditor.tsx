import { useCallback, useState } from "react";
import { FolderOpen, Plus, Trash2 } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { GovernancePathPicker } from "@/components/GovernancePathPicker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  GovernanceApprovalUser,
  GovernanceFileGrant,
} from "@/lib/api";
import {
  isFileApprovalUser,
  selectedFileApproverKeys,
  validateGovernanceFileGrants,
} from "@/lib/governance-file-approvals";

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
  approvalUsers?: GovernanceApprovalUser[];
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
    mode: "none" | "direct" | "approval",
  ) => {
    if (mode === "none") {
      update(index, {
        write: false,
        write_requires_approval: false,
        write_approval_roles: [],
        write_approval_users: [],
        read: true,
      });
      return;
    }
    if (mode === "direct") {
      update(index, {
        write: true,
        write_requires_approval: false,
        write_approval_roles: [],
        write_approval_users: [],
      });
      return;
    }
    update(index, {
      write: true,
      write_requires_approval: true,
      write_approval_roles: [],
      write_approval_users: [],
    });
  };

  const toggleApprover = (
    index: number,
    grant: GovernanceFileGrant,
    value: string,
  ) => {
    const current = selectedFileApproverKeys(
      grant,
      approvalUsers,
      approvalRoles,
    );
    const next = current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value];
    update(index, {
      write_requires_approval: true,
      write_approval_roles: [],
      write_approval_users: next,
    });
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
              (grant.write_requires_approval === true ||
                (grant.write_approval_roles?.length ?? 0) > 0 ||
                (grant.write_approval_users?.length ?? 0) > 0);
            const writeMode = !grant.write
              ? "none"
              : approvalRequired
                ? "approval"
                : "direct";
            const selectedApprovalUsers = selectedFileApproverKeys(
              grant,
              approvalUsers,
              approvalRoles,
            );
            const approvalCandidates = approvalUsers.filter(
              (user) =>
                isFileApprovalUser(user, approvalRoles) ||
                selectedApprovalUsers.includes(user.actor_key),
            );
            const approvalError = validateGovernanceFileGrants(
              [grant],
              approvalUsers,
              approvalRoles,
            );
            return (
              <div
                key={index}
                className="space-y-4 border border-border bg-background p-4"
              >
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
                    label="Include files and subfolders"
                    checked={grant.recursive}
                    disabled={disabled}
                    onChange={(recursive) => update(index, { recursive })}
                  />
                </div>

                {writeMode === "approval" && (
                  <div className="grid gap-4 border border-border bg-muted/20 p-4">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Select approvers
                      </div>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">
                        Only governed managers and administrators are available.
                        Choose at least one person before saving.
                      </p>
                      <div className="mt-3 grid max-h-40 gap-2 overflow-y-auto sm:grid-cols-2">
                        {approvalCandidates.map((user) => (
                          <ApprovalToggle
                            key={user.actor_key}
                            label={`${user.name || user.actor_key} · ${user.actor_key}`}
                            checked={selectedApprovalUsers.includes(
                              user.actor_key,
                            )}
                            disabled={disabled}
                            onChange={() =>
                              toggleApprover(index, grant, user.actor_key)
                            }
                          />
                        ))}
                        {approvalCandidates.length === 0 && (
                          <span className="text-xs text-muted-foreground">
                            Add a governed manager or administrator before using
                            write after approval.
                          </span>
                        )}
                      </div>
                    </div>
                    {approvalError && (
                      <div className="border border-red-500/40 bg-red-500/5 p-3 text-xs leading-5 text-red-600 dark:text-red-400">
                        {approvalError}
                      </div>
                    )}
                    <p className="text-xs leading-5 text-muted-foreground">
                      This approval checkpoint belongs to the matching path
                      policy. It applies to every non-approver who can write
                      this same path. A selected approver can inspect and execute
                      the reviewed edit on this path. Raw terminal and code
                      writes remain read-only so they cannot bypass review.
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
