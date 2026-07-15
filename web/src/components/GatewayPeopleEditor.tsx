import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ChevronRight,
  Pencil,
  Plus,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { GovernanceFileGrantEditor } from "@/components/GovernanceFileGrantEditor";
import { RoleMultiSelect, TeamMultiSelect } from "@/components/GovernanceFields";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { GovernanceUser } from "@/lib/api";
import {
  normalizeGatewayPersonId,
  type GatewayPersonDraft,
} from "@/lib/gateway-people";

function clonePerson(row: GatewayPersonDraft): GatewayPersonDraft {
  return {
    ...row,
    roles: [...row.roles],
    teams: [...row.teams],
    file_access: row.file_access.map((grant) => ({ ...grant })),
  };
}

function newPerson(roles: string[]): GatewayPersonDraft {
  return {
    user_id: "",
    name: "",
    roles: [...roles],
    teams: [],
    governed: false,
    file_access: [],
  };
}

export function GatewayPeopleEditor({
  platform,
  allowKey,
  rows,
  disabled,
  saving,
  configured,
  defaultRoles,
  roleOptions,
  teamOptions,
  approvalUsers,
  userIdPlaceholder,
  userIdHelp,
  onSave,
}: {
  platform: { id: string; name: string };
  allowKey: string;
  rows: GatewayPersonDraft[];
  disabled: boolean;
  saving: boolean;
  configured: boolean;
  defaultRoles: string[];
  roleOptions: string[];
  teamOptions: string[];
  approvalUsers: GovernanceUser[];
  userIdPlaceholder: string;
  userIdHelp: string[];
  onSave: (rows: GatewayPersonDraft[]) => Promise<boolean>;
}) {
  const [dialog, setDialog] = useState<{
    index: number | null;
    row: GatewayPersonDraft;
  } | null>(null);
  const closeDialog = useCallback(() => setDialog(null), []);

  const savePerson = async (row: GatewayPersonDraft) => {
    if (!dialog) return;
    const nextRows =
      dialog.index === null
        ? [...rows, row]
        : rows.map((current, index) => (index === dialog.index ? row : current));
    if (await onSave(nextRows)) closeDialog();
  };

  const removePerson = async () => {
    if (dialog?.index === null || dialog?.index === undefined) return;
    if (!window.confirm(`Remove ${dialog.row.name || dialog.row.user_id} from ${platform.name}?`)) {
      return;
    }
    const nextRows = rows.filter((_, index) => index !== dialog.index);
    if (await onSave(nextRows)) closeDialog();
  };

  const openNew = () => setDialog({ index: null, row: newPerson(defaultRoles) });

  return (
    <div className="border border-border/70 bg-muted/10 p-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
            <Users className="h-3.5 w-3.5" />
            People and Governance
          </div>
          <p className="mt-2 max-w-3xl text-xs normal-case leading-5 text-muted-foreground">
            Saved {platform.name} people stay in this compact list. Add a person or select an existing one to open
            the focused editor for identity, role, teams, and direct file access. Saving updates both
            <code> {allowKey}</code> and Governance.
          </p>
          {!configured && (
            <p className="mt-2 text-xs normal-case leading-5 text-warning">
              You can prepare and save people now, but access only takes effect after the connection credentials
              above are configured and the gateway is running.
            </p>
          )}
        </div>
        <Button size="sm" outlined className="shrink-0" onClick={openNew} disabled={disabled}>
          <Plus className="h-4 w-4" />
          Add person
        </Button>
      </div>

      {rows.length === 0 ? (
        <button
          type="button"
          className="mt-4 flex min-h-24 w-full items-center justify-between gap-4 border border-dashed border-border bg-background px-4 py-3 text-left normal-case hover:border-primary/50 hover:bg-primary/[0.025]"
          onClick={openNew}
          disabled={disabled}
        >
          <span>
            <span className="block text-sm font-semibold text-foreground">No people added yet</span>
            <span className="mt-1 block text-xs leading-5 text-muted-foreground">
              Add yourself first. On a fresh installation, the first saved person is protected as admin.
            </span>
          </span>
          <Plus className="h-5 w-5 shrink-0 text-primary" />
        </button>
      ) : (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {rows.map((row, index) => (
            <button
              key={`${row.user_id}:${index}`}
              type="button"
              className="group flex min-h-28 w-full items-start justify-between gap-4 border border-border bg-background p-4 text-left normal-case transition-colors hover:border-primary/50 hover:bg-primary/[0.025]"
              onClick={() => setDialog({ index, row: clonePerson(row) })}
              disabled={disabled}
              aria-label={`Edit ${row.name || row.user_id}`}
            >
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold text-foreground">
                    {row.name || row.user_id}
                  </span>
                  <span className={row.governed ? "text-xs text-success" : "text-xs text-warning"}>
                    {row.governed ? "Active" : "Needs role"}
                  </span>
                </span>
                <code className="mt-1 block truncate text-xs text-muted-foreground">
                  {platform.id}:{row.user_id}
                </code>
                <span className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span>{row.roles.length ? row.roles.join(", ") : "No role"}</span>
                  <span>{row.teams.length} team{row.teams.length === 1 ? "" : "s"}</span>
                  <span>{row.file_access.length} path{row.file_access.length === 1 ? "" : "s"}</span>
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-1 text-xs font-semibold text-primary">
                <Pencil className="h-3.5 w-3.5" />
                Edit
                <ChevronRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="mt-4 border-t border-border/60 pt-4 text-xs normal-case leading-5 text-muted-foreground">
        Use the list for quick people management, or open{" "}
        <Link to="/governance?section=people" className="font-bold text-primary hover:underline">
          Governance / People
        </Link>{" "}
        for ongoing review and advanced policy changes.
      </div>

      {dialog && (
        <GatewayPersonDialog
          platform={platform}
          row={dialog.row}
          editing={dialog.index !== null}
          existingRows={rows}
          editingIndex={dialog.index}
          roleOptions={roleOptions}
          teamOptions={teamOptions}
          approvalUsers={approvalUsers}
          userIdPlaceholder={userIdPlaceholder}
          userIdHelp={userIdHelp}
          saving={saving}
          onClose={closeDialog}
          onSave={savePerson}
          onRemove={dialog.index === null ? undefined : removePerson}
        />
      )}
    </div>
  );
}

function GatewayPersonDialog({
  platform,
  row,
  editing,
  existingRows,
  editingIndex,
  roleOptions,
  teamOptions,
  approvalUsers,
  userIdPlaceholder,
  userIdHelp,
  saving,
  onClose,
  onSave,
  onRemove,
}: {
  platform: { id: string; name: string };
  row: GatewayPersonDraft;
  editing: boolean;
  existingRows: GatewayPersonDraft[];
  editingIndex: number | null;
  roleOptions: string[];
  teamOptions: string[];
  approvalUsers: GovernanceUser[];
  userIdPlaceholder: string;
  userIdHelp: string[];
  saving: boolean;
  onClose: () => void;
  onSave: (row: GatewayPersonDraft) => Promise<void>;
  onRemove?: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(() => clonePerson(row));
  const [idHelpOpen, setIdHelpOpen] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const normalizedId = normalizeGatewayPersonId(platform.id, draft.user_id);
  const duplicate = existingRows.some(
    (candidate, index) =>
      index !== editingIndex &&
      normalizeGatewayPersonId(platform.id, candidate.user_id) === normalizedId,
  );
  const validationError = !normalizedId
    ? `Enter a valid ${platform.name} user ID.`
    : duplicate
      ? "This person is already in the list."
      : !draft.name.trim()
        ? "Display name is required."
        : draft.roles.length === 0
          ? "Select at least one Governance role."
          : null;
  const changed = JSON.stringify(draft) !== JSON.stringify(row);
  const requestClose = useCallback(() => {
    if (saving) return;
    if (changed && !window.confirm("Discard the unsaved changes in this person editor?")) return;
    onClose();
  }, [changed, onClose, saving]);
  const requestCloseRef = useRef(requestClose);

  useEffect(() => {
    requestCloseRef.current = requestClose;
  }, [requestClose]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement as HTMLElement | null;
    document.body.style.overflow = "hidden";
    dialogRef.current?.querySelector<HTMLInputElement>("input")?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        requestCloseRef.current();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus?.();
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-stretch justify-center bg-background/85 backdrop-blur-sm sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="gateway-person-dialog-title"
      onClick={(event) => {
        if (event.target === event.currentTarget) requestClose();
      }}
    >
      <div ref={dialogRef} className="flex max-h-full w-full max-w-4xl flex-col border border-border bg-card shadow-2xl sm:max-h-[90vh]">
        <header className="flex items-start justify-between gap-4 border-b border-border p-4 sm:px-5">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.08em] text-primary">
              {editing ? "Edit person" : "Add person"} · {platform.name}
            </div>
            <h2 id="gateway-person-dialog-title" className="mt-1 text-base font-semibold normal-case text-foreground">
              {editing ? draft.name || draft.user_id : "Configure identity and access"}
            </h2>
            <p className="mt-1 text-xs normal-case leading-5 text-muted-foreground">
              Saving updates the messaging allowlist and Governance together.
            </p>
          </div>
          <Button ghost size="icon" onClick={requestClose} disabled={saving} aria-label="Close person editor">
            <X className="h-4 w-4" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-4 sm:p-5">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid content-start gap-2">
              <span className="flex items-center gap-2">
                <Label>{platform.name} user ID</Label>
                {userIdHelp.length > 0 && (
                  <button
                    type="button"
                    className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-border text-[0.65rem] font-bold text-muted-foreground hover:border-primary hover:text-primary"
                    aria-label={`How to find a ${platform.name} user ID`}
                    aria-expanded={idHelpOpen}
                    onClick={() => setIdHelpOpen((open) => !open)}
                  >
                    ?
                  </button>
                )}
              </span>
              <Input
                value={draft.user_id}
                placeholder={userIdPlaceholder}
                onChange={(event) => setDraft((current) => ({ ...current, user_id: event.target.value }))}
                autoComplete="off"
                disabled={saving}
              />
              {idHelpOpen && userIdHelp.length > 0 && (
                <div className="border border-border/60 bg-muted/30 p-3 text-xs normal-case leading-5 text-muted-foreground">
                  <ul className="list-disc space-y-1 pl-4">
                    {userIdHelp.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              )}
            </label>
            <label className="grid content-start gap-2">
              <Label>Display name</Label>
              <Input
                value={draft.name}
                placeholder="Ana Finance"
                onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                disabled={saving}
              />
              <span className="text-xs normal-case text-muted-foreground">
                Used in audit and administration views.
              </span>
            </label>
          </div>

          <div className="grid gap-5 border border-border p-4 md:grid-cols-2">
            <div className="grid content-start gap-2 normal-case">
              <Label>Role</Label>
              <RoleMultiSelect
                value={draft.roles}
                onChange={(roles) => setDraft((current) => ({ ...current, roles }))}
                options={roleOptions}
                disabled={saving}
                emptyHint="Select at least one role"
              />
              <span className="text-xs text-muted-foreground">
                Assign the narrowest role that covers this person&apos;s work.
              </span>
            </div>
            <div className="grid content-start gap-2 normal-case">
              <Label>Teams</Label>
              <TeamMultiSelect
                value={draft.teams}
                onChange={(teams) => setDraft((current) => ({ ...current, teams }))}
                options={teamOptions}
                disabled={saving}
              />
              <span className="text-xs text-muted-foreground">
                Optional membership for shared team policies and knowledge.
              </span>
            </div>
          </div>

          <GovernanceFileGrantEditor
            grants={draft.file_access}
            onChange={(file_access) => setDraft((current) => ({ ...current, file_access }))}
            approvalRoles={roleOptions}
            approvalUsers={approvalUsers}
            title="Direct file and folder access"
            description="Add only the server paths this person needs. Team access can be managed later in Governance."
            disabled={saving}
          />
        </div>

        <footer className="flex flex-col gap-3 border-t border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div>
            {validationError && (
              <div className="flex items-center gap-2 text-xs normal-case text-warning">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                {validationError}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {onRemove && (
              <Button ghost destructive onClick={() => void onRemove()} disabled={saving}>
                <Trash2 className="h-4 w-4" />
                Remove
              </Button>
            )}
            <Button outlined onClick={requestClose} disabled={saving}>Cancel</Button>
            <Button
              onClick={() =>
                void onSave({
                  ...draft,
                  user_id: normalizedId,
                  name: draft.name.trim(),
                })
              }
              disabled={Boolean(validationError) || saving}
            >
              {saving ? <Spinner className="h-4 w-4" /> : null}
              {editing ? "Save changes" : "Add person"}
            </Button>
          </div>
        </footer>
      </div>
    </div>
  );
}
