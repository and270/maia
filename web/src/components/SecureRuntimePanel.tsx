import { useEffect, useState } from "react";
import {
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
  TerminalSquare,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { useLocation } from "react-router-dom";
import type { GovernanceSandboxStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

export function SecureRuntimePanel({
  status,
  loading = false,
  onSetup,
  onRefresh,
  defaultExpanded = false,
}: {
  status: GovernanceSandboxStatus;
  loading?: boolean;
  onSetup?: () => void;
  onRefresh?: () => void;
  defaultExpanded?: boolean;
}) {
  const { hash } = useLocation();
  const [copied, setCopied] = useState<string | null>(null);
  const restricted = !status.ready;
  const canProvisionImage =
    Boolean(onSetup) &&
    status.can_auto_setup &&
    ["image_missing", "image_unusable", "image_check_failed"].includes(status.status);

  useEffect(() => {
    if (hash !== "#secure-runtime") return;
    const frame = window.requestAnimationFrame(() => {
      document
        .getElementById("secure-runtime")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [hash]);

  const copyCommand = async (command: string) => {
    await navigator.clipboard.writeText(command);
    setCopied(command);
    window.setTimeout(() => setCopied((current) => (current === command ? null : current)), 1600);
  };

  return (
    <section
      id="secure-runtime"
      className={cn(
        "scroll-mt-4 border p-4 normal-case",
        restricted
          ? "border-warning/45 bg-warning/[0.045]"
          : "border-success/40 bg-success/[0.045]",
      )}
      aria-label="Secure runtime status"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center border",
              restricted
                ? "border-warning/40 text-warning"
                : "border-success/40 text-success",
            )}
          >
            {restricted ? <TerminalSquare className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-foreground">Secure runtime</h3>
              <Badge tone={restricted ? "warning" : "success"}>
                {restricted ? "Restricted mode" : "Full automation"}
              </Badge>
              <Badge tone="outline">{status.platform_label}</Badge>
              {status.runtime && <Badge tone="secondary">{status.runtime}</Badge>}
            </div>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">
              {status.message}
            </p>
          </div>
        </div>
        <div className="flex w-full shrink-0 flex-col gap-2 sm:w-auto sm:flex-row">
          {canProvisionImage && (
            <Button size="sm" onClick={onSetup} disabled={loading} className="w-full sm:w-auto">
              {loading ? <Spinner className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
              Finish setup
            </Button>
          )}
          {onRefresh && (
            <Button size="sm" outlined onClick={onRefresh} disabled={loading} className="w-full sm:w-auto">
              {loading ? <Spinner className="h-4 w-4" /> : <RefreshCw className="h-4 w-4" />}
              Check again
            </Button>
          )}
          <a
            href={status.docs_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex w-full items-center justify-center gap-2 border border-current/25 px-3 py-2 text-xs font-bold uppercase tracking-[0.08em] text-midground transition-opacity hover:opacity-80 sm:w-auto"
          >
            Setup guide
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
      </div>

      {restricted && (
        <details
          key={`${status.platform}-${status.status}`}
          className="mt-4 border-t border-border/70 pt-4"
          open={defaultExpanded}
        >
          <summary className="cursor-pointer text-sm font-semibold text-foreground">
            Setup steps, operating impact, and verification
          </summary>

          <div className="mt-4">
            <p className="text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
              Why it matters
            </p>
            <p className="mt-2 max-w-5xl text-sm leading-6 text-muted-foreground">{status.why}</p>
          </div>

          <div className="mt-4 flex min-w-0 flex-col gap-2 border-t border-border/70 pt-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
                Guided setup from the Maia host
              </p>
              <code className="mt-1 block break-all text-sm">{status.setup_command}</code>
            </div>
            <Button
              size="sm"
              outlined
              className="w-full shrink-0 sm:w-auto"
              onClick={() => void copyCommand(status.setup_command)}
            >
              {copied === status.setup_command ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              {copied === status.setup_command ? "Copied" : "Copy command"}
            </Button>
          </div>

          <div className="mt-4 grid gap-4 border-t border-border/70 pt-4 md:grid-cols-2">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.08em] text-success">Available now</p>
              <ul className="mt-2 space-y-2 text-sm leading-5 text-muted-foreground">
                {status.available_capabilities.map((item) => (
                  <li key={item} className="flex items-start gap-2">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.08em] text-warning">
                Blocked until configured
              </p>
              <ul className="mt-2 space-y-2 text-sm leading-5 text-muted-foreground">
                {status.blocked_capabilities.map((item) => (
                  <li key={item} className="flex items-start gap-2">
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 bg-warning" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="mt-4 border-t border-border/70 pt-4">
            <p className="text-sm font-semibold text-foreground">
              Set up full automation on {status.platform_label}
            </p>
            <ol className="mt-4 space-y-4">
              {status.steps.map((step, index) => (
                <li key={`${step.title}-${index}`} className="grid gap-3 sm:grid-cols-[2rem_minmax(0,1fr)]">
                  <span className="flex h-7 w-7 items-center justify-center border border-current/25 text-xs font-bold">
                    {index + 1}
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-foreground">{step.title}</p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">{step.detail}</p>
                    {step.command && (
                      <div className="mt-2 flex min-w-0 flex-col gap-2 border border-border bg-background p-2 sm:flex-row sm:items-center sm:justify-between">
                        <code className="min-w-0 break-all text-xs">{step.command}</code>
                        <Button
                          size="sm"
                          outlined
                          className="w-full shrink-0 sm:w-auto"
                          onClick={() => void copyCommand(step.command!)}
                        >
                          {copied === step.command ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                          {copied === step.command ? "Copied" : "Copy"}
                        </Button>
                      </div>
                    )}
                    {step.url && (
                      <a
                        href={step.url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-primary underline underline-offset-4"
                      >
                        Official instructions <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ol>
            <p className="mt-4 text-xs leading-5 text-muted-foreground">
              Maia never falls back to unrestricted host execution. After the runtime is ready, retry the same
              request; no new file grant or gateway restart is required.
            </p>
          </div>
        </details>
      )}

      {!restricted && (
        <div className="mt-4 border-t border-border/70 pt-4">
          <p className="text-xs font-bold uppercase tracking-[0.08em] text-muted-foreground">
            Why it matters
          </p>
          <p className="mt-2 max-w-5xl text-sm leading-6 text-muted-foreground">{status.why}</p>
        </div>
      )}
    </section>
  );
}
