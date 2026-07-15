import { useEffect } from "react";
import { AlertTriangle, Save } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";

export function UnsavedChangesBar({
  dirty,
  saving = false,
  onSave,
  label = "Unsaved changes",
  description = "Review and save before leaving this page.",
  saveLabel = "Save changes",
}: {
  dirty: boolean;
  saving?: boolean;
  onSave: () => void;
  label?: string;
  description?: string;
  saveLabel?: string;
}) {
  useEffect(() => {
    if (!dirty) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [dirty]);

  if (!dirty) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[70] flex w-[min(32rem,calc(100vw-2rem))] flex-col gap-3 border border-warning/50 bg-background p-4 normal-case shadow-2xl sm:flex-row sm:items-center sm:justify-between lg:right-6">
      <div className="flex min-w-0 items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
        <div className="min-w-0">
          <div className="text-sm font-semibold text-foreground">{label}</div>
          <div className="mt-0.5 text-xs leading-5 text-muted-foreground">{description}</div>
        </div>
      </div>
      <Button size="sm" onClick={onSave} disabled={saving} className="shrink-0">
        {saving ? <Spinner className="h-4 w-4" /> : <Save className="h-4 w-4" />}
        {saving ? "Saving…" : saveLabel}
      </Button>
    </div>
  );
}
