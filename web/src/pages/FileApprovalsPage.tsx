import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, FileCheck, RefreshCw, XCircle } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/NouiTypography";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Toast } from "@/components/Toast";
import { api } from "@/lib/api";
import type { FileChangeApproval } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { PluginSlot } from "@/plugins";

const STATUS_FILTERS = ["pending", "approved", "denied", "stale"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

function formatDate(value?: string | null): string {
  if (!value) return "Never";
  return new Date(value).toLocaleString();
}

function statusTone(
  status: string,
): "secondary" | "success" | "destructive" | "warning" {
  if (status === "approved") return "success";
  if (status === "denied") return "destructive";
  if (status === "stale") return "warning";
  return "secondary";
}

function diffLineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) {
    return "text-muted-foreground";
  }
  if (line.startsWith("@@")) return "text-sky-500";
  if (line.startsWith("+")) return "text-emerald-500";
  if (line.startsWith("-")) return "text-red-500";
  return "text-muted-foreground";
}

function DiffView({ diff }: { diff?: string }) {
  if (!diff) {
    return (
      <div className="text-xs text-muted-foreground">No diff available.</div>
    );
  }
  return (
    <pre className="max-h-80 overflow-auto border border-border bg-muted/30 p-2 font-mono-ui text-xs leading-5">
      {diff.split("\n").map((line, idx) => (
        <div key={idx} className={diffLineClass(line)}>
          {line || " "}
        </div>
      ))}
    </pre>
  );
}

function ApproverBadges({ approval }: { approval: FileChangeApproval }) {
  const roles = approval.requirement?.roles ?? [];
  const users = approval.requirement?.users ?? [];
  const eligible = approval.eligible_approvers ?? [];
  if (roles.length === 0 && users.length === 0 && eligible.length === 0)
    return null;
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
      <span>Approvers:</span>
      {roles.map((role) => (
        <Badge key={`role-${role}`} tone="warning">
          role: {role}
        </Badge>
      ))}
      {users.map((user) => (
        <Badge key={`user-${user}`} tone="outline">
          {user}
        </Badge>
      ))}
      {eligible.length > 0 && <span className="ml-2">Eligible now:</span>}
      {eligible.map((actorKey) => (
        <Badge key={`eligible-${actorKey}`} tone="success">
          {actorKey}
        </Badge>
      ))}
    </div>
  );
}

export default function FileApprovalsPage({
  embedded = false,
}: {
  embedded?: boolean;
}) {
  const [approvals, setApprovals] = useState<FileChangeApproval[]>([]);
  const [status, setStatus] = useState<StatusFilter>("pending");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const { toast, showToast } = useToast();

  const load = useCallback(
    (nextStatus: StatusFilter = status) => {
      setLoading(true);
      api
        .getFileChangeApprovals(nextStatus)
        .then((data) => setApprovals(data.approvals))
        .catch((err) =>
          showToast(`Failed to load file approvals: ${err}`, "error"),
        )
        .finally(() => setLoading(false));
    },
    [showToast, status],
  );

  useEffect(() => {
    load(status);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const decide = async (approval: FileChangeApproval, approve: boolean) => {
    const note = approve ? "" : window.prompt("Reason for denial") || "";
    setBusyId(approval.id);
    try {
      await api.decideFileChangeApproval(approval.id, { approve, note });
      showToast(
        `${approve ? "Approved" : "Denied"} change to ${
          approval.display_path || approval.path
        }`,
        "success",
      );
      load();
    } catch (err) {
      showToast(`Decision failed: ${err}`, "error");
    } finally {
      setBusyId(null);
    }
  };

  if (loading && approvals.length === 0) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner className="text-2xl text-primary" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {!embedded && <PluginSlot name="file-approvals:top" />}
      <Toast toast={toast} />

      <section className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          {!embedded && (
            <H2
              variant="sm"
              className="flex items-center gap-2 text-muted-foreground"
            >
              <FileCheck className="h-4 w-4" />
              File Change Approvals
            </H2>
          )}
          <div className="flex items-center gap-2">
            <div className="flex gap-1">
              {STATUS_FILTERS.map((filter) => (
                <Button
                  key={filter}
                  size="sm"
                  ghost={status !== filter}
                  onClick={() => setStatus(filter)}
                >
                  {filter}
                </Button>
              ))}
            </div>
            <Button onClick={() => load()} disabled={loading} size="sm">
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
          </div>
        </div>
        <p className="text-xs normal-case leading-5 text-muted-foreground">
          Explicit staged-file workflows appear here until an approver accepts
          them. Interactive writes governed by approval roles use a natural
          handoff to an authorized writer in the shared conversation and do not
          create a card. For records shown here, approving applies the exact
          reviewed content; if the file changed on disk after staging, the
          request is marked stale instead. Related policy is configured in{" "}
          <Link
            to="/governance?section=files"
            className="font-bold text-primary hover:underline"
          >
            Governance / File access
          </Link>
          .
        </p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <FileCheck className="h-4 w-4" />
            {status === "pending" ? "Pending Changes" : `${status} changes`}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {approvals.length === 0 ? (
            <div className="py-8 text-center text-sm normal-case text-muted-foreground">
              No {status} file changes.
            </div>
          ) : (
            <div className="grid gap-3">
              {approvals.map((approval) => (
                <div
                  key={approval.id}
                  className="flex flex-col gap-3 border border-border bg-muted/20 p-3 normal-case"
                >
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={statusTone(approval.status)}>
                          {approval.status}
                        </Badge>
                        <Badge tone="outline">
                          {approval.operation === "replace_file"
                            ? approval.base_exists
                              ? "generated replacement"
                              : "generated file"
                            : approval.base_exists
                              ? "text edit"
                              : "new text file"}
                        </Badge>
                        <span className="break-all font-mono-ui text-xs">
                          {approval.display_path || approval.path}
                        </span>
                      </div>
                      <ApproverBadges approval={approval} />
                      <div className="text-xs text-muted-foreground">
                        Requested by {approval.requested_by?.id || "unknown"} at{" "}
                        {formatDate(approval.created_at)}
                        {approval.origin?.platform
                          ? ` via ${approval.origin.platform}${
                              approval.origin.chat_name
                                ? ` (${approval.origin.chat_name})`
                                : ""
                            }`
                          : ""}
                      </div>
                      {approval.decided_at && (
                        <div className="text-xs text-muted-foreground">
                          Decided by {approval.decided_by?.id || "unknown"} at{" "}
                          {formatDate(approval.decided_at)}
                          {approval.decision_note
                            ? ` — ${approval.decision_note}`
                            : ""}
                        </div>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <Button
                        size="sm"
                        ghost
                        onClick={() =>
                          setExpandedId(
                            expandedId === approval.id ? null : approval.id,
                          )
                        }
                      >
                        {expandedId === approval.id
                          ? approval.artifact
                            ? "Hide details"
                            : "Hide diff"
                          : approval.artifact
                            ? "View details"
                            : "View diff"}
                      </Button>
                      {approval.status === "pending" && (
                        <>
                          <Button
                            size="sm"
                            onClick={() => decide(approval, true)}
                            disabled={busyId === approval.id}
                          >
                            <CheckCircle2 className="h-4 w-4" />
                            Approve
                          </Button>
                          <Button
                            size="sm"
                            ghost
                            onClick={() => decide(approval, false)}
                            disabled={busyId === approval.id}
                          >
                            <XCircle className="h-4 w-4" />
                            Deny
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                  {expandedId === approval.id && (
                    <DiffView diff={approval.diff} />
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {!embedded && <PluginSlot name="file-approvals:bottom" />}
    </div>
  );
}
