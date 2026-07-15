import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

export function OnboardingReturnBar({
  step,
  title,
}: {
  step: number;
  title: string;
}) {
  const [params] = useSearchParams();
  if (params.get("from") !== "onboarding") return null;

  return (
    <div className="flex flex-col gap-3 border border-primary/30 bg-primary/5 p-3 normal-case sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center border border-primary/40 text-xs font-bold text-primary">
          {step}
        </span>
        <div>
          <div className="text-sm font-semibold text-foreground">Onboarding · {title}</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
            Your changes stay here while you review this step.
          </div>
        </div>
      </div>
      <Link
        to="/onboarding"
        className="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-[0.08em] text-primary hover:underline"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to onboarding
      </Link>
    </div>
  );
}
