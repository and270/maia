import { useCallback, useEffect, useState, type ComponentType } from "react";
import {
  CheckCircle2,
  Database,
  FileText,
  RefreshCw,
  ShieldCheck,
  Users,
  XCircle,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/NouiTypography";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Toast } from "@/components/Toast";
import { api } from "@/lib/api";
import type {
  KnowledgeApproval,
  KnowledgeCorporateLayer,
  KnowledgeLayersResponse,
  KnowledgeTeamLayer,
} from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { PluginSlot } from "@/plugins";

function formatDate(value?: string | null): string {
  if (!value) return "Never";
  return new Date(value).toLocaleString();
}

function scopeTone(scope: string): "secondary" | "warning" {
  return scope === "corporate" ? "warning" : "secondary";
}

function preview(value?: string | null): string {
  if (!value) return "No content preview";
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > 180 ? `${compact.slice(0, 180)}...` : compact;
}

function LayerCard({
  icon: Icon,
  title,
  layer,
}: {
  icon: ComponentType<{ className?: string }>;
  title: string;
  layer: KnowledgeCorporateLayer | KnowledgeTeamLayer;
}) {
  const name = "name" in layer ? layer.name : title;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Icon className="h-4 w-4" />
          {name}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm normal-case">
        <div className="flex flex-wrap gap-2">
          <Badge tone={layer.memory_exists ? "success" : "outline"}>
            {layer.memory_exists ? "Memory ready" : "No memory file"}
          </Badge>
          <Badge tone="secondary">{layer.skill_count} skills</Badge>
        </div>
        <div className="space-y-1 text-xs leading-5 text-muted-foreground">
          <div className="truncate">
            <span className="text-foreground">Memory:</span> {layer.memory_path}
          </div>
          <div className="truncate">
            <span className="text-foreground">Skills:</span> {layer.skills_dir}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function KnowledgePage() {
  const [layers, setLayers] = useState<KnowledgeLayersResponse | null>(null);
  const [approvals, setApprovals] = useState<KnowledgeApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const { toast, showToast } = useToast();

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.getKnowledgeLayers(), api.getKnowledgeApprovals("pending")])
      .then(([layerData, approvalData]) => {
        setLayers(layerData);
        setApprovals(approvalData.approvals);
      })
      .catch((err) => showToast(`Failed to load knowledge: ${err}`, "error"))
      .finally(() => setLoading(false));
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (approval: KnowledgeApproval, approve: boolean) => {
    const note = approve ? "" : window.prompt("Reason for denial") || "";
    setBusyId(approval.id);
    try {
      await api.decideKnowledgeApproval(approval.id, { approve, note });
      showToast(`${approve ? "Approved" : "Denied"} ${approval.kind} change`, "success");
      load();
    } catch (err) {
      showToast(`Decision failed: ${err}`, "error");
    } finally {
      setBusyId(null);
    }
  };

  if (loading && !layers) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner className="text-2xl text-primary" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PluginSlot name="knowledge:top" />
      <Toast toast={toast} />

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={layers?.enabled ? "success" : "destructive"}>
            {layers?.enabled ? "Enabled" : "Disabled"}
          </Badge>
          <Badge tone="secondary">{layers?.pending_approvals ?? 0} pending</Badge>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <H2 variant="sm" className="flex items-center gap-2 text-muted-foreground">
            <Database className="h-4 w-4" />
            Knowledge Governance
          </H2>
          <Button onClick={load} disabled={loading} size="sm">
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        </div>
      </section>

      {layers && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <LayerCard icon={ShieldCheck} title="Corporate" layer={layers.corporate} />
          {layers.teams.map((team) => (
            <LayerCard key={team.name} icon={Users} title={team.name} layer={team} />
          ))}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <FileText className="h-4 w-4" />
                User Layer
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-xs normal-case leading-5 text-muted-foreground">
              <div className="truncate">
                <span className="text-foreground">Memory:</span> {layers.user.memory_dir}
              </div>
              <div className="truncate">
                <span className="text-foreground">Skills:</span> {layers.user.skills_dir}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4" />
            Pending Approvals
          </CardTitle>
        </CardHeader>
        <CardContent>
          {approvals.length === 0 ? (
            <div className="py-8 text-center text-sm normal-case text-muted-foreground">
              No pending knowledge changes.
            </div>
          ) : (
            <div className="grid gap-3">
              {approvals.map((approval) => (
                <div
                  key={approval.id}
                  className="flex flex-col gap-3 border border-border bg-muted/20 p-3 normal-case lg:flex-row lg:items-start lg:justify-between"
                >
                  <div className="min-w-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={scopeTone(approval.scope)}>
                        {approval.scope}
                        {approval.team ? `:${approval.team}` : ""}
                      </Badge>
                      <Badge tone="outline">{approval.kind}</Badge>
                      <Badge tone="secondary">{approval.action}</Badge>
                      {approval.name && <span className="font-mono-ui text-xs">{approval.name}</span>}
                    </div>
                    <p className="text-sm leading-6 text-muted-foreground">
                      {approval.note || preview(approval.content || approval.old_text)}
                    </p>
                    <div className="text-xs text-muted-foreground">
                      Requested by {approval.requested_by?.id || "unknown"} at{" "}
                      {formatDate(approval.created_at)}
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-2">
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
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <PluginSlot name="knowledge:bottom" />
    </div>
  );
}
