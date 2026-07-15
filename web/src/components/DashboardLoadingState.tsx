import { Database } from "lucide-react";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { cn } from "@/lib/utils";

export function DashboardLoadingState({
  title = "Loading saved dashboard state",
  description = "Restoring your saved settings. This can take a moment after opening or refreshing the dashboard.",
  cards = 3,
  className,
}: {
  title?: string;
  description?: string;
  cards?: number;
  className?: string;
}) {
  return (
    <section
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={cn(
        "relative min-h-[22rem] overflow-hidden border border-primary/25 bg-primary/[0.025] p-5 normal-case sm:p-7",
        className,
      )}
    >
      <div className="absolute inset-x-0 top-0 h-0.5 animate-pulse bg-primary" aria-hidden />

      <div className="flex max-w-2xl items-start gap-4">
        <div className="relative flex h-11 w-11 shrink-0 items-center justify-center border border-primary/30 bg-background">
          <Database className="h-4 w-4 text-primary/60" />
          <Spinner className="absolute -bottom-1 -right-1 h-4 w-4 bg-background text-primary" />
        </div>
        <div>
          <div className="text-base font-semibold text-foreground">{title}</div>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p>
        </div>
      </div>

      <div
        className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
        aria-hidden="true"
      >
        {Array.from({ length: cards }, (_, index) => (
          <div
            key={index}
            className="min-h-32 animate-pulse border border-border/70 bg-background p-4"
            style={{ animationDelay: `${index * 110}ms` }}
          >
            <div className="h-3 w-24 bg-muted-foreground/20" />
            <div className="mt-5 h-2.5 w-full bg-muted-foreground/10" />
            <div className="mt-2 h-2.5 w-4/5 bg-muted-foreground/10" />
            <div className="mt-6 h-7 w-28 bg-primary/10" />
          </div>
        ))}
      </div>

      <div className="mt-5 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
        Reading saved configuration and current service status
      </div>
    </section>
  );
}
