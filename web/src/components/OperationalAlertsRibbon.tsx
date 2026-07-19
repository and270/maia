import { useEffect, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Container,
  MessageSquare,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useSidebarStatus } from "@/hooks/useSidebarStatus";
import {
  api,
  type GovernanceSandboxStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const RUNTIME_POLL_MS = 30_000;
const ENGINE_UNAVAILABLE = new Set([
  "daemon_timeout",
  "daemon_unavailable",
]);
const IMAGE_UNAVAILABLE = new Set([
  "image_missing",
  "image_unusable",
  "image_check_failed",
]);

type RuntimeAlertCopy = {
  action: string;
  detail: ReactNode;
  title: string;
};

function runtimeAlertCopy(status: GovernanceSandboxStatus): RuntimeAlertCopy {
  const runtimeName =
    status.runtime === "docker"
      ? "Docker"
      : status.runtime === "podman"
        ? "Podman"
        : "Docker/Podman";

  if (
    status.runtime === "podman" &&
    status.platform === "macos" &&
    ENGINE_UNAVAILABLE.has(status.status)
  ) {
    return {
      title: "Podman security runtime is not running.",
      detail: (
        <>
          Start the existing machine with{" "}
          <code className="whitespace-nowrap font-semibold">
            podman machine start
          </code>
          . Initialize a new machine only if Podman reports that none exists.
        </>
      ),
      action: "Open Podman recovery",
    };
  }

  if (
    status.runtime === "docker" &&
    ["macos", "windows_wsl"].includes(status.platform) &&
    ENGINE_UNAVAILABLE.has(status.status)
  ) {
    return {
      title: "Docker security runtime is not running.",
      detail:
        status.platform === "windows_wsl"
          ? "Open or reopen Docker Desktop in Windows, wait for its engine, and confirm WSL integration."
          : "Open or reopen Docker Desktop and wait until its engine reports Running.",
      action: "Open Docker recovery",
    };
  }

  if (
    status.runtime === "docker" &&
    status.platform === "linux" &&
    ENGINE_UNAVAILABLE.has(status.status)
  ) {
    return {
      title: "Docker security runtime is not running.",
      detail:
        "Start or restart Docker Engine, verify that the Maia user can reach it, then check again.",
      action: "Open Docker recovery",
    };
  }

  if (status.status === "wsl_integration_disabled") {
    return {
      title: "Docker security runtime needs WSL access.",
      detail:
        "Docker Desktop is running, but Maia's Linux distribution is not enabled under WSL Integration.",
      action: "Open Docker setup",
    };
  }

  if (IMAGE_UNAVAILABLE.has(status.status)) {
    return {
      title: `${runtimeName} is running, but Maia's security image is not ready.`,
      detail: status.remediation,
      action: `Finish ${runtimeName} setup`,
    };
  }

  if (status.status === "not_found") {
    return {
      title: "Docker/Podman security is not configured.",
      detail: status.remediation,
      action: "Configure Docker/Podman",
    };
  }

  return {
    title: "Secure command runtime is not ready.",
    detail: status.remediation || status.message,
    action: `Open ${runtimeName} setup`,
  };
}

function AlertItem({
  action,
  detail,
  icon: Icon,
  title,
  to,
}: {
  action: string;
  detail: ReactNode;
  icon: typeof MessageSquare;
  title: string;
  to: string;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2 border-warning/30 py-1 sm:flex-row sm:items-center sm:justify-between sm:gap-4 xl:border-l xl:pl-4">
      <div className="flex min-w-0 items-start gap-2">
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
        <p className="min-w-0 text-xs leading-5 text-foreground">
          <span className="font-semibold">{title}</span>{" "}
          <span className="text-muted-foreground">{detail}</span>
        </p>
      </div>
      <Link
        to={to}
        className={cn(
          "inline-flex shrink-0 items-center gap-1.5 self-start",
          "text-xs font-bold uppercase tracking-[0.06em] text-primary",
          "underline decoration-current/40 underline-offset-4",
          "transition-opacity hover:opacity-75",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
          "sm:self-center",
        )}
      >
        {action}
        <ArrowRight className="h-3.5 w-3.5" />
      </Link>
    </div>
  );
}

export function OperationalAlertsRibbon({
  gatewayConfigured,
}: {
  gatewayConfigured: boolean;
}) {
  const status = useSidebarStatus();
  const [runtimeStatus, setRuntimeStatus] =
    useState<GovernanceSandboxStatus | null>(null);

  useEffect(() => {
    let active = true;

    const loadRuntimeStatus = () => {
      api
        .getSecureRuntimeStatus()
        .then((next) => {
          if (active) setRuntimeStatus(next);
        })
        .catch(() => {
          // A failed health request should not manufacture a false warning.
        });
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") loadRuntimeStatus();
    };
    const refreshFromEvent = () => loadRuntimeStatus();

    loadRuntimeStatus();
    const interval = window.setInterval(loadRuntimeStatus, RUNTIME_POLL_MS);
    window.addEventListener("focus", refreshFromEvent);
    window.addEventListener(
      "maia:secure-runtime-updated",
      refreshFromEvent,
    );
    document.addEventListener("visibilitychange", refreshWhenVisible);

    return () => {
      active = false;
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshFromEvent);
      window.removeEventListener(
        "maia:secure-runtime-updated",
        refreshFromEvent,
      );
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, []);

  const gatewayOffline =
    gatewayConfigured &&
    status !== null &&
    !status.gateway_running &&
    status.gateway_state !== "starting";
  const runtimeUnavailable =
    runtimeStatus !== null && !runtimeStatus.ready;

  if (!gatewayOffline && !runtimeUnavailable) return null;

  const runtimeCopy = runtimeUnavailable
    ? runtimeAlertCopy(runtimeStatus)
    : null;

  return (
    <aside
      aria-label="Operational alerts"
      aria-live="polite"
      className="relative z-2 shrink-0 border-b border-warning/45 bg-warning/[0.08] px-3 py-2 normal-case sm:px-6"
    >
      <div className="flex flex-col gap-2 xl:flex-row xl:items-center">
        <div className="flex shrink-0 items-center gap-2 text-xs font-bold uppercase tracking-[0.08em] text-warning">
          <AlertTriangle className="h-4 w-4" />
          Attention
        </div>
        <div
          className={cn(
            "grid min-w-0 flex-1 gap-2 xl:gap-4",
            gatewayOffline && runtimeUnavailable && "2xl:grid-cols-2",
          )}
        >
          {gatewayOffline && (
            <AlertItem
              icon={MessageSquare}
              title={
                status?.gateway_state === "startup_failed"
                  ? "The configured Gateway failed to start."
                  : "The Gateway is configured but not running."
              }
              detail="Slack, Discord, and other connected channels cannot reach Maia until it starts."
              action="Go to Gateway to start"
              to="/gateway"
            />
          )}
          {runtimeCopy && (
            <AlertItem
              icon={Container}
              title={runtimeCopy.title}
              detail={runtimeCopy.detail}
              action={runtimeCopy.action}
              to="/onboarding#secure-runtime"
            />
          )}
        </div>
      </div>
    </aside>
  );
}
