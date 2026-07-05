import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle2,
  Clock,
  Pause,
  Play,
  Plus,
  ShieldCheck,
  Trash2,
  XCircle,
  Zap,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/NouiTypography";
import { api } from "@/lib/api";
import type { CronJob } from "@/lib/api";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { useToast } from "@/hooks/useToast";
import { useConfirmDelete } from "@/hooks/useConfirmDelete";
import { Toast } from "@/components/Toast";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/i18n";
import {
  HelpBox,
  HelpDot,
  RoleMultiSelect,
  useGovernanceOptions,
} from "@/components/GovernanceFields";
import { PluginSlot } from "@/plugins";

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString();
}

const STATUS_TONE: Record<string, "success" | "warning" | "destructive"> = {
  enabled: "success",
  scheduled: "success",
  paused: "warning",
  awaiting_authorization: "warning",
  authorization_denied: "destructive",
  error: "destructive",
  completed: "destructive",
};

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function CronPage() {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(true);
  const { toast, showToast } = useToast();
  const { t } = useI18n();

  // New job form state
  const [prompt, setPrompt] = useState("");
  const [schedule, setSchedule] = useState("");
  const [name, setName] = useState("");
  const [deliver, setDeliver] = useState("local");
  const [requiresApproval, setRequiresApproval] = useState(false);
  const [approvalRoles, setApprovalRoles] = useState<string[]>(["admin"]);
  const [approvalUsers, setApprovalUsers] = useState("");
  const [creating, setCreating] = useState(false);
  const [scheduleHelpOpen, setScheduleHelpOpen] = useState(false);
  const [approverHelpOpen, setApproverHelpOpen] = useState(false);
  const { roles: roleOptions } = useGovernanceOptions();

  const loadJobs = useCallback(() => {
    api
      .getCronJobs()
      .then(setJobs)
      .catch(() => showToast(t.common.loading, "error"))
      .finally(() => setLoading(false));
  }, [showToast, t.common.loading]);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  const handleCreate = async () => {
    if (!prompt.trim() || !schedule.trim()) {
      showToast(`${t.cron.prompt} & ${t.cron.schedule} required`, "error");
      return;
    }
    setCreating(true);
    try {
      await api.createCronJob({
        prompt: prompt.trim(),
        schedule: schedule.trim(),
        name: name.trim() || undefined,
        deliver,
        authorization: requiresApproval
          ? {
              required: true,
              roles: approvalRoles,
              users: splitList(approvalUsers),
            }
          : undefined,
      });
      showToast(t.common.create + " ✓", "success");
      setPrompt("");
      setSchedule("");
      setName("");
      setDeliver("local");
      setRequiresApproval(false);
      setApprovalRoles(["admin"]);
      setApprovalUsers("");
      loadJobs();
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setCreating(false);
    }
  };

  const handlePauseResume = async (job: CronJob) => {
    try {
      const isPaused = job.state === "paused";
      if (isPaused) {
        await api.resumeCronJob(job.id);
        showToast(
          `${t.cron.resume}: "${job.name || job.prompt.slice(0, 30)}"`,
          "success",
        );
      } else {
        await api.pauseCronJob(job.id);
        showToast(
          `${t.cron.pause}: "${job.name || job.prompt.slice(0, 30)}"`,
          "success",
        );
      }
      loadJobs();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const handleTrigger = async (job: CronJob) => {
    try {
      await api.triggerCronJob(job.id);
      showToast(
        `${t.cron.triggerNow}: "${job.name || job.prompt.slice(0, 30)}"`,
        "success",
      );
      loadJobs();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const handleAuthorization = async (job: CronJob, approve: boolean) => {
    const note = approve ? "" : window.prompt("Reason for denial") || "";
    try {
      await api.authorizeCronJob(job.id, { approve, note });
      showToast(
        `${approve ? "Approved" : "Denied"}: "${job.name || job.prompt.slice(0, 30)}"`,
        "success",
      );
      loadJobs();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const jobDelete = useConfirmDelete({
    onDelete: useCallback(
      async (id: string) => {
        const job = jobs.find((j) => j.id === id);
        try {
          await api.deleteCronJob(id);
          showToast(
            `${t.common.delete}: "${job?.name || (job?.prompt ?? "").slice(0, 30) || id}"`,
            "success",
          );
          loadJobs();
        } catch (e) {
          showToast(`${t.status.error}: ${e}`, "error");
          throw e;
        }
      },
      [jobs, loadJobs, showToast, t.common.delete, t.status.error],
    ),
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner className="text-2xl text-primary" />
      </div>
    );
  }

  const pendingJob = jobDelete.pendingId
    ? jobs.find((j) => j.id === jobDelete.pendingId)
    : null;

  return (
    <div className="flex flex-col gap-6">
      <PluginSlot name="cron:top" />
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={jobDelete.isOpen}
        onCancel={jobDelete.cancel}
        onConfirm={jobDelete.confirm}
        title={t.cron.confirmDeleteTitle}
        description={
          pendingJob
            ? `"${pendingJob.name || pendingJob.prompt.slice(0, 40)}" — ${t.cron.confirmDeleteMessage}`
            : t.cron.confirmDeleteMessage
        }
        loading={jobDelete.isDeleting}
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Plus className="h-4 w-4" />
            {t.cron.newJob}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="cron-name">{t.cron.nameOptional}</Label>
              <Input
                id="cron-name"
                placeholder={t.cron.namePlaceholder}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="cron-prompt">{t.cron.prompt}</Label>
              <textarea
                id="cron-prompt"
                className="flex min-h-[80px] w-full border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder={t.cron.promptPlaceholder}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="grid gap-2">
                <div className="flex items-center gap-1.5">
                  <Label htmlFor="cron-schedule">{t.cron.schedule}</Label>
                  <HelpDot
                    ariaLabel="How to write a cron schedule"
                    open={scheduleHelpOpen}
                    onToggle={() => setScheduleHelpOpen((open) => !open)}
                  />
                </div>
                <Input
                  id="cron-schedule"
                  placeholder={t.cron.schedulePlaceholder}
                  value={schedule}
                  onChange={(e) => setSchedule(e.target.value)}
                />
                {scheduleHelpOpen && (
                  <HelpBox>
                    <p>
                      Five fields: minute, hour, day of month, month, day of
                      week. Examples:
                    </p>
                    <ul className="mt-1 list-disc space-y-1 pl-4">
                      <li>
                        <code>0 9 * * MON</code> — Mondays at 09:00
                      </li>
                      <li>
                        <code>*/30 * * * *</code> — every 30 minutes
                      </li>
                      <li>
                        <code>0 8 1 * *</code> — the 1st of each month at 08:00
                      </li>
                      <li>
                        <code>0 18 * * MON-FRI</code> — weekdays at 18:00
                      </li>
                    </ul>
                  </HelpBox>
                )}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="cron-deliver">{t.cron.deliverTo}</Label>
                <Select
                  id="cron-deliver"
                  value={deliver}
                  onValueChange={(v) => setDeliver(v)}
                >
                  <SelectOption value="local">
                    {t.cron.delivery.local}
                  </SelectOption>
                  <SelectOption value="telegram">
                    {t.cron.delivery.telegram}
                  </SelectOption>
                  <SelectOption value="discord">
                    {t.cron.delivery.discord}
                  </SelectOption>
                  <SelectOption value="slack">
                    {t.cron.delivery.slack}
                  </SelectOption>
                  <SelectOption value="email">
                    {t.cron.delivery.email}
                  </SelectOption>
                </Select>
              </div>

              <div className="flex items-end">
                <Button
                  onClick={handleCreate}
                  disabled={creating}
                  prefix={<Plus />}
                  className="w-full"
                >
                  {creating ? t.common.creating : t.common.create}
                </Button>
              </div>
            </div>

            <div className="grid gap-3 border-t border-border pt-4">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={requiresApproval}
                  onChange={(e) => setRequiresApproval(e.target.checked)}
                  className="size-4 accent-current"
                />
                <span className="flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4" />
                  Require human approval before each run
                </span>
              </label>

              {requiresApproval && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="cron-approval-roles">
                      Approver roles
                    </Label>
                    <RoleMultiSelect
                      value={approvalRoles}
                      onChange={setApprovalRoles}
                      options={roleOptions}
                      emptyHint="pick who can authorize runs"
                    />
                  </div>
                  <div className="grid gap-2">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor="cron-approval-users">
                        Approver users
                      </Label>
                      <HelpDot
                        ariaLabel="Approver user key format and where roles come from"
                        open={approverHelpOpen}
                        onToggle={() => setApproverHelpOpen((open) => !open)}
                      />
                    </div>
                    <Input
                      id="cron-approval-users"
                      placeholder="slack:U123, telegram:987654"
                      value={approvalUsers}
                      onChange={(e) => setApprovalUsers(e.target.value)}
                    />
                    {approverHelpOpen && (
                      <HelpBox>
                        When the job becomes due it pauses until someone with
                        an approver role, or one of these exact users,
                        authorizes it. Users are actor keys in the{" "}
                        <code>&lt;platform&gt;:&lt;user id&gt;</code> format
                        (e.g. <code>slack:U01ABC2DEF3</code>) — copy them from
                        the platform&apos;s users editor in{" "}
                        <Link
                          to="/gateway"
                          className="font-bold text-primary hover:underline"
                        >
                          Gateway
                        </Link>{" "}
                        or from{" "}
                        <Link
                          to="/dashboard-access"
                          className="font-bold text-primary hover:underline"
                        >
                          Access
                        </Link>
                        . Roles come from the governance hierarchy.
                      </HelpBox>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3">
        <H2
          variant="sm"
          className="flex items-center gap-2 text-muted-foreground"
        >
          <Clock className="h-4 w-4" />
          {t.cron.scheduledJobs} ({jobs.length})
        </H2>

        {jobs.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              {t.cron.noJobs}
            </CardContent>
          </Card>
        )}

        {jobs.map((job) => (
          <Card key={job.id}>
            <CardContent className="flex items-center gap-4 py-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm truncate">
                    {job.name ||
                      job.prompt.slice(0, 60) +
                        (job.prompt.length > 60 ? "..." : "")}
                  </span>
                  <Badge tone={STATUS_TONE[job.state] ?? "secondary"}>
                    {job.state}
                  </Badge>
                  {job.deliver && job.deliver !== "local" && (
                    <Badge tone="outline">{job.deliver}</Badge>
                  )}
                  {job.authorization?.required && (
                    <Badge tone="warning">
                      auth: {job.authorization.status || "pending"}
                    </Badge>
                  )}
                </div>
                {job.name && (
                  <p className="text-xs text-muted-foreground truncate mb-1">
                    {job.prompt.slice(0, 100)}
                    {job.prompt.length > 100 ? "..." : ""}
                  </p>
                )}
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="font-mono">{job.schedule_display}</span>
                  <span>
                    {t.cron.last}: {formatTime(job.last_run_at)}
                  </span>
                  <span>
                    {t.cron.next}: {formatTime(job.next_run_at)}
                  </span>
                </div>
                {job.last_error && (
                  <p className="text-xs text-destructive mt-1">
                    {job.last_error}
                  </p>
                )}
                {job.paused_reason && (
                  <p className="text-xs text-warning mt-1">
                    {job.paused_reason}
                  </p>
                )}
                {job.authorization?.required && (
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {(job.authorization.roles ?? []).length > 0 && (
                      <span>
                        Roles: {(job.authorization.roles ?? []).join(", ")}
                      </span>
                    )}
                    {(job.authorization.users ?? []).length > 0 && (
                      <span>
                        Users: {(job.authorization.users ?? []).join(", ")}
                      </span>
                    )}
                    {job.authorization.approved_by && (
                      <span>Approved by: {job.authorization.approved_by}</span>
                    )}
                    {job.authorization.denied_by && (
                      <span>Denied by: {job.authorization.denied_by}</span>
                    )}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-1 shrink-0">
                {job.state === "awaiting_authorization" ? (
                  <>
                    <Button
                      ghost
                      size="icon"
                      title="Approve"
                      aria-label="Approve"
                      onClick={() => handleAuthorization(job, true)}
                      className="text-success"
                    >
                      <CheckCircle2 />
                    </Button>
                    <Button
                      ghost
                      destructive
                      size="icon"
                      title="Deny"
                      aria-label="Deny"
                      onClick={() => handleAuthorization(job, false)}
                    >
                      <XCircle />
                    </Button>
                  </>
                ) : (
                  <Button
                    ghost
                    size="icon"
                    title={
                      job.state === "paused" ? t.cron.resume : t.cron.pause
                    }
                    aria-label={
                      job.state === "paused" ? t.cron.resume : t.cron.pause
                    }
                    onClick={() => handlePauseResume(job)}
                    className={
                      job.state === "paused" ? "text-success" : "text-warning"
                    }
                  >
                    {job.state === "paused" ? <Play /> : <Pause />}
                  </Button>
                )}

                <Button
                  ghost
                  size="icon"
                  title={t.cron.triggerNow}
                  aria-label={t.cron.triggerNow}
                  onClick={() => handleTrigger(job)}
                  disabled={job.state === "awaiting_authorization"}
                >
                  <Zap />
                </Button>

                <Button
                  ghost
                  destructive
                  size="icon"
                  title={t.common.delete}
                  aria-label={t.common.delete}
                  onClick={() => jobDelete.requestDelete(job.id)}
                >
                  <Trash2 />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <PluginSlot name="cron:bottom" />
    </div>
  );
}
