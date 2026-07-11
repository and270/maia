import { Plus, Trash2 } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { GovernanceFileGrant } from "@/lib/api";

export function GovernanceFileGrantEditor({
  grants,
  onChange,
  title = "Direct file and folder access",
  description = "Grant only the paths required for this identity's work.",
  disabled = false,
}: {
  grants: GovernanceFileGrant[];
  onChange: (grants: GovernanceFileGrant[]) => void;
  title?: string;
  description?: string;
  disabled?: boolean;
}) {
  const add = () =>
    onChange([
      ...grants,
      { path: "", recursive: true, read: true, write: false },
    ]);

  const update = (index: number, patch: Partial<GovernanceFileGrant>) =>
    onChange(
      grants.map((grant, position) =>
        position === index ? { ...grant, ...patch } : grant,
      ),
    );

  const remove = (index: number) =>
    onChange(grants.filter((_, position) => position !== index));

  return (
    <section className="space-y-3 border-t border-border pt-5 normal-case">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
        </div>
        <Button size="sm" onClick={add} disabled={disabled}>
          <Plus className="h-4 w-4" />
          Add file or folder
        </Button>
      </div>

      {grants.length === 0 ? (
        <div className="border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
          No direct paths. Access can still come from role or team policies.
        </div>
      ) : (
        <div className="divide-y divide-border border border-border">
          {grants.map((grant, index) => (
            <div
              key={`${grant.path}-${index}`}
              className="grid gap-3 p-3 md:grid-cols-[minmax(14rem,1fr)_auto_auto_auto_auto] md:items-end"
            >
              <label className="grid gap-2">
                <Label>Server path</Label>
                <Input
                  value={grant.path}
                  onChange={(event) => update(index, { path: event.target.value })}
                  placeholder="/srv/company/finance or /srv/company/plan.pdf"
                  disabled={disabled}
                />
              </label>
              <GrantToggle
                label="Read"
                checked={grant.read}
                disabled={disabled}
                onChange={(read) => {
                  if (!read && !grant.write) return;
                  update(index, { read });
                }}
              />
              <GrantToggle
                label="Write"
                checked={grant.write}
                disabled={disabled}
                onChange={(write) => {
                  if (!write && !grant.read) return;
                  update(index, { write });
                }}
              />
              <GrantToggle
                label="Include children"
                checked={grant.recursive}
                disabled={disabled}
                onChange={(recursive) => update(index, { recursive })}
              />
              <Button
                size="icon"
                ghost
                onClick={() => remove(index)}
                disabled={disabled}
                aria-label={`Remove access for ${grant.path || "new path"}`}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function GrantToggle({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled: boolean;
}) {
  return (
    <label className="flex min-h-10 items-center gap-2 text-xs text-muted-foreground">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
      />
      {label}
    </label>
  );
}
