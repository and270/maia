import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Ban,
  Check,
  KeyRound,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  HelpBox,
  HelpDot,
  RoleMultiSelect,
  TeamMultiSelect,
  TeamsHelpContent,
} from "@/components/GovernanceFields";
import { useGovernanceOptions } from "@/hooks/useGovernanceOptions";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/NouiTypography";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import {
  api,
  type DashboardAccessRequest,
  type DashboardAccessResponse,
  type DashboardAccessRevocation,
} from "@/lib/api";
import { PluginSlot } from "@/plugins";

type RequestDraft = {
  name: string;
  roles: string;
  teams: string;
  note: string;
  denyReason: string;
  revokeReason: string;
};

function textToList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function timestamp(value?: number): string {
  if (!value) return "unknown";
  return new Date(value * 1000).toLocaleString();
}

function statusTone(status: string): "success" | "warning" | "destructive" | "secondary" {
  if (status === "approved") return "success";
  if (status === "pending") return "warning";
  if (status === "denied" || status === "revoked") return "destructive";
  return "secondary";
}

function requestDisplayName(request: DashboardAccessRequest): string {
  return request.actor?.user_name || request.actor_key;
}

function defaultDraft(request: DashboardAccessRequest): RequestDraft {
  return {
    name: requestDisplayName(request),
    roles: (request.approved_roles ?? []).join(", ") || "manager",
    teams: (request.approved_teams ?? []).join(", "),
    note: "",
    denyReason: "",
    revokeReason: "",
  };
}

export default function DashboardAccessPage() {
  const [data, setData] = useState<DashboardAccessResponse | null>(null);
  const [drafts, setDrafts] = useState<Record<string, RequestDraft>>({});
  const [manualActor, setManualActor] = useState("");
  const [manualReason, setManualReason] = useState("");
  const [actorHelpOpen, setActorHelpOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const { toast, showToast } = useToast();
  const { roles: roleOptions, teams: teamOptions } = useGovernanceOptions();

  const load = useCallback(() => {
    setLoading(true);
    api
      .getDashboardAccessRequests()
      .then((resp) => {
        setData(resp);
        setDrafts((current) => {
          const next = { ...current };
          for (const request of resp.requests) {
            if (!next[request.id]) next[request.id] = defaultDraft(request);
          }
          return next;
        });
      })
      .catch((err) => showToast(`Failed to load dashboard access: ${err}`, "error"))
      .finally(() => setLoading(false));
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  const updateDraft = (id: string, patch: Partial<RequestDraft>) => {
    setDrafts((current) => ({
      ...current,
      [id]: { ...(current[id] ?? defaultDraft({ id, actor_key: id, status: "pending" })), ...patch },
    }));
  };

  const approve = async (request: DashboardAccessRequest) => {
    const draft = drafts[request.id] ?? defaultDraft(request);
    const roles = textToList(draft.roles);
    if (!roles.length) {
      showToast("Assign at least one dashboard role before approval.", "error");
      return;
    }
    setBusy(`approve:${request.id}`);
    try {
      await api.approveDashboardAccessRequest(request.id, {
        name: draft.name,
        roles,
        teams: textToList(draft.teams),
        note: draft.note,
      });
      showToast(`Approved ${request.actor_key}`, "success");
      load();
    } catch (err) {
      showToast(`Approval failed: ${err}`, "error");
    } finally {
      setBusy("");
    }
  };

  const deny = async (request: DashboardAccessRequest) => {
    const draft = drafts[request.id] ?? defaultDraft(request);
    setBusy(`deny:${request.id}`);
    try {
      await api.denyDashboardAccessRequest(request.id, draft.denyReason);
      showToast(`Denied ${request.actor_key}`, "success");
      load();
    } catch (err) {
      showToast(`Denial failed: ${err}`, "error");
    } finally {
      setBusy("");
    }
  };

  const revoke = async (actorKey: string, reason: string) => {
    if (!actorKey.trim()) {
      showToast("Actor key is required.", "error");
      return;
    }
    setBusy(`revoke:${actorKey}`);
    try {
      await api.revokeDashboardAccess(actorKey.trim(), reason);
      showToast(`Revoked dashboard access for ${actorKey}`, "success");
      setManualActor("");
      setManualReason("");
      load();
    } catch (err) {
      showToast(`Revocation failed: ${err}`, "error");
    } finally {
      setBusy("");
    }
  };

  const restore = async (actorKey: string) => {
    setBusy(`restore:${actorKey}`);
    try {
      await api.restoreDashboardAccess(actorKey);
      showToast(`Restored dashboard access for ${actorKey}`, "success");
      load();
    } catch (err) {
      showToast(`Restore failed: ${err}`, "error");
    } finally {
      setBusy("");
    }
  };

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner className="text-2xl text-primary" />
      </div>
    );
  }

  const requests = data?.requests ?? [];
  const pending = requests.filter((request) => request.status === "pending");
  const decided = requests.filter((request) => request.status !== "pending");
  const revoked = data?.revoked_users ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PluginSlot name="dashboard-access:top" />
      <Toast toast={toast} />

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="outline">Protected dashboard</Badge>
          <Badge tone="warning">{pending.length} pending</Badge>
          <Badge tone="destructive">{revoked.length} revoked</Badge>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <H2 variant="sm" className="flex items-center gap-2 text-muted-foreground">
            <ShieldCheck className="h-4 w-4" />
            Dashboard Access
          </H2>
          <Button size="sm" onClick={load} disabled={loading}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        </div>
        <p className="max-w-3xl text-sm normal-case leading-6 text-muted-foreground">
          Governed users can request dashboard access with /dashboard from a private
          channel chat. New gateway users must first receive a role in Config /
          Governance; allowlisting alone cannot reach this request flow. Admins review
          requests here and can revoke future dashboard logins at any time.
        </p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <KeyRound className="h-4 w-4" />
            Pending Requests
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          {pending.map((request) => (
            <AccessRequestCard
              key={request.id}
              request={request}
              draft={drafts[request.id] ?? defaultDraft(request)}
              busy={busy}
              roleOptions={roleOptions}
              teamOptions={teamOptions}
              onDraft={(patch) => updateDraft(request.id, patch)}
              onApprove={() => approve(request)}
              onDeny={() => deny(request)}
            />
          ))}
          {pending.length === 0 && (
            <p className="text-sm normal-case leading-6 text-muted-foreground">
              No pending dashboard access requests.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Ban className="h-4 w-4" />
            Revoke Access
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 normal-case md:grid-cols-[1fr_1fr_auto]">
          <div className="space-y-2">
            <div className="flex items-center gap-1.5">
              <Label>Actor key</Label>
              <HelpDot
                ariaLabel="What an actor key is and where to find it"
                open={actorHelpOpen}
                onToggle={() => setActorHelpOpen((open) => !open)}
              />
            </div>
            <Input
              value={manualActor}
              onChange={(event) => setManualActor(event.target.value)}
              placeholder="discord:99887766"
            />
          </div>
          <Field label="Reason" value={manualReason} onChange={setManualReason} placeholder="Role change" />
          <Button
            className="self-end"
            size="sm"
            onClick={() => revoke(manualActor, manualReason)}
            disabled={busy === `revoke:${manualActor}`}
          >
            <Ban className="h-4 w-4" />
            Revoke
          </Button>
          {actorHelpOpen && (
            <div className="md:col-span-3">
              <HelpBox>
                The actor key is the identity Maia uses everywhere:{" "}
                <code>&lt;platform&gt;:&lt;user id&gt;</code>, e.g.{" "}
                <code>slack:U01ABC2DEF3</code> or <code>discord:99887766</code>.
                Copy it from a request card above, from Recent Decisions below,
                or from the platform&apos;s users editor in{" "}
                <Link to="/gateway" className="font-bold text-primary hover:underline">
                  Gateway
                </Link>
                .
              </HelpBox>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Recent Decisions</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            {decided.map((request) => (
              <DecisionRow
                key={request.id}
                request={request}
                draft={drafts[request.id] ?? defaultDraft(request)}
                busy={busy}
                onDraft={(patch) => updateDraft(request.id, patch)}
                onRevoke={() =>
                  revoke(request.actor_key, (drafts[request.id] ?? defaultDraft(request)).revokeReason)
                }
              />
            ))}
            {decided.length === 0 && (
              <p className="text-sm normal-case leading-6 text-muted-foreground">
                Approved, denied, and revoked requests will appear here.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Revoked Actors</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            {revoked.map((entry) => (
              <RevokedRow
                key={entry.actor_key}
                entry={entry}
                busy={busy}
                onRestore={() => restore(entry.actor_key)}
              />
            ))}
            {revoked.length === 0 && (
              <p className="text-sm normal-case leading-6 text-muted-foreground">
                No dashboard actors are currently revoked.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <PluginSlot name="dashboard-access:bottom" />
    </div>
  );
}

function AccessRequestCard({
  busy,
  draft,
  onApprove,
  onDeny,
  onDraft,
  request,
  roleOptions,
  teamOptions,
}: {
  busy: string;
  draft: RequestDraft;
  onApprove: () => void;
  onDeny: () => void;
  onDraft: (patch: Partial<RequestDraft>) => void;
  request: DashboardAccessRequest;
  roleOptions: string[];
  teamOptions: string[];
}) {
  const [teamsHelpOpen, setTeamsHelpOpen] = useState(false);
  return (
    <div className="grid gap-4 border border-border p-4 normal-case lg:grid-cols-2">
      <div className="space-y-2 lg:col-span-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={statusTone(request.status)}>{request.status}</Badge>
          <span className="font-mono-ui text-sm text-foreground">{request.actor_key}</span>
        </div>
        <p className="text-xs leading-5 text-muted-foreground">
          Requested {timestamp(request.requested_at)} from {request.actor?.platform ?? "channel"}.
          The user gets a one-time login token only after approval and a new /dashboard request.
        </p>
      </div>
      <Field label="Name" value={draft.name} onChange={(value) => onDraft({ name: value })} />
      <div className="space-y-2">
        <Label>Access level (roles)</Label>
        <RoleMultiSelect
          value={textToList(draft.roles)}
          onChange={(roles) => onDraft({ roles: roles.join(", ") })}
          options={roleOptions}
          emptyHint="pick at least one role"
        />
      </div>
      <div className="space-y-2">
        <div className="flex items-center gap-1.5">
          <Label>Teams</Label>
          <HelpDot
            ariaLabel="What teams are and where they are managed"
            open={teamsHelpOpen}
            onToggle={() => setTeamsHelpOpen((open) => !open)}
          />
        </div>
        <TeamMultiSelect
          value={textToList(draft.teams)}
          onChange={(value) => onDraft({ teams: value.join(", ") })}
          options={teamOptions}
        />
        {teamsHelpOpen && (
          <HelpBox>
            <TeamsHelpContent existingTeams={teamOptions} />
          </HelpBox>
        )}
      </div>
      <Field label="Approval note" value={draft.note} onChange={(value) => onDraft({ note: value })} />
      <Field
        label="Denial reason"
        value={draft.denyReason}
        onChange={(value) => onDraft({ denyReason: value })}
        placeholder="No dashboard access required"
      />
      <div className="flex items-end gap-2">
        <Button size="sm" onClick={onApprove} disabled={busy === `approve:${request.id}`}>
          <Check className="h-4 w-4" />
          Approve
        </Button>
        <Button size="sm" onClick={onDeny} disabled={busy === `deny:${request.id}`}>
          <X className="h-4 w-4" />
          Deny
        </Button>
      </div>
    </div>
  );
}

function DecisionRow({
  busy,
  draft,
  onDraft,
  onRevoke,
  request,
}: {
  busy: string;
  draft: RequestDraft;
  onDraft: (patch: Partial<RequestDraft>) => void;
  onRevoke: () => void;
  request: DashboardAccessRequest;
}) {
  return (
    <div className="grid gap-3 border border-border p-3 normal-case">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(request.status)}>{request.status}</Badge>
            <span className="font-mono-ui text-sm text-foreground">{request.actor_key}</span>
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Updated {timestamp(request.updated_at)}
            {request.reviewed_by_key ? ` by ${request.reviewed_by_key}` : ""}
          </p>
        </div>
      </div>
      {request.status === "approved" && (
        <div className="grid gap-2 md:grid-cols-[1fr_auto]">
          <Field
            label="Revocation reason"
            value={draft.revokeReason}
            onChange={(value) => onDraft({ revokeReason: value })}
            placeholder="No longer team lead"
          />
          <Button
            className="self-end"
            size="sm"
            onClick={onRevoke}
            disabled={busy === `revoke:${request.actor_key}`}
          >
            <Ban className="h-4 w-4" />
            Revoke
          </Button>
        </div>
      )}
    </div>
  );
}

function RevokedRow({
  busy,
  entry,
  onRestore,
}: {
  busy: string;
  entry: DashboardAccessRevocation;
  onRestore: () => void;
}) {
  return (
    <div className="flex flex-col gap-3 border border-border p-3 normal-case sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="font-mono-ui text-sm text-foreground">{entry.actor_key}</div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          Revoked {timestamp(entry.revoked_at)}
          {entry.reason ? `: ${entry.reason}` : ""}
        </p>
      </div>
      <Button size="sm" onClick={onRestore} disabled={busy === `restore:${entry.actor_key}`}>
        <RotateCcw className="h-4 w-4" />
        Restore
      </Button>
    </div>
  );
}

function Field({
  label,
  onChange,
  placeholder,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  placeholder?: string;
  value: string;
}) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <Input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
      {label === "Roles" || label === "Teams" ? (
        <p className="text-xs text-muted-foreground">Comma-separated.</p>
      ) : null}
    </div>
  );
}
