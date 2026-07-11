import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

/**
 * Shared building blocks for governance-aware forms, so every page offers
 * the same UX: role choices come from governance.role_hierarchy instead of
 * free-typed commas, team fields suggest existing team names, and "?" dots
 * explain non-obvious values with links to where they are managed.
 */

export const DEFAULT_ROLE_OPTIONS = ["viewer", "operator", "manager", "admin"];

/** Fetch governance role/team vocabulary once for a page. */
export function useGovernanceOptions(): { roles: string[]; teams: string[] } {
  const [roles, setRoles] = useState<string[]>([]);
  const [teams, setTeams] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .getGovernanceOptions()
      .then((resp) => {
        if (cancelled) return;
        setRoles(resp.roles ?? []);
        setTeams(resp.teams ?? []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return { roles, teams };
}

/** The small round "?" toggle used next to field labels. */
export function HelpDot({
  ariaLabel,
  open,
  onToggle,
}: {
  ariaLabel: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-border text-[0.65rem] font-bold text-muted-foreground hover:border-primary hover:text-primary"
      aria-label={ariaLabel}
      aria-expanded={open}
      onClick={(event) => {
        event.preventDefault();
        onToggle();
      }}
    >
      ?
    </button>
  );
}

/** The explanatory box a HelpDot toggles. */
export function HelpBox({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-sm border border-border/60 bg-muted/30 p-3 text-xs normal-case leading-5 text-muted-foreground">
      {children}
    </div>
  );
}

/**
 * Toggleable role chips driven by the configured role hierarchy. Roles in
 * `value` that are not in the configured list are preserved as extra chips
 * instead of being dropped.
 */
export function RoleMultiSelect({
  value,
  onChange,
  options,
  disabled,
  emptyHint,
}: {
  value: string[];
  onChange: (roles: string[]) => void;
  options: string[];
  disabled?: boolean;
  emptyHint?: string;
}) {
  const base = options.length ? options : DEFAULT_ROLE_OPTIONS;
  const extras = value.filter((role) => !base.includes(role));
  const all = [...base, ...extras];
  const selected = new Set(value);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {all.map((role) => {
        const on = selected.has(role);
        return (
          <button
            key={role}
            type="button"
            disabled={disabled}
            aria-pressed={on}
            className={
              on
                ? "border border-midground bg-midground px-2.5 py-1 font-mono-ui text-xs text-background-base"
                : "border border-border bg-transparent px-2.5 py-1 font-mono-ui text-xs text-muted-foreground hover:border-primary hover:text-primary"
            }
            onClick={(event) => {
              event.preventDefault();
              const next = new Set(selected);
              if (on) {
                next.delete(role);
              } else {
                next.add(role);
              }
              onChange([...next]);
            }}
          >
            {role}
          </button>
        );
      })}
      {emptyHint && value.length === 0 && (
        <span className="text-xs normal-case text-muted-foreground">{emptyHint}</span>
      )}
    </div>
  );
}

/** Standard explanation of teams, with links to where they are managed. */
export function TeamsHelpContent({ existingTeams }: { existingTeams: string[] }) {
  return (
    <>
      <p>
        Teams group users for shared knowledge and folder access. A team
        exists as soon as something references it — just type a name
        (comma-separate several). What each team can reach is managed in{" "}
        <Link to="/governance?section=files" className="font-bold text-primary hover:underline">
          Governance / File access
        </Link>{" "}
        and team knowledge in{" "}
        <Link to="/knowledge" className="font-bold text-primary hover:underline">
          Knowledge
        </Link>
        ; assignments live under <code>governance.users</code> in{" "}
        <Link to="/governance?section=people" className="font-bold text-primary hover:underline">
          Governance / People
        </Link>
        .
      </p>
      {existingTeams.length > 0 && (
        <p className="mt-1">Existing teams: {existingTeams.join(", ")}.</p>
      )}
    </>
  );
}

/** Teams text input with datalist suggestions from existing team names. */
export function TeamsInput({
  value,
  onChange,
  options,
  listId,
  placeholder = "engineering, finance",
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  listId: string;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <>
      <Input
        list={listId}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="off"
        disabled={disabled}
      />
      <datalist id={listId}>
        {options.map((team) => (
          <option key={team} value={team} />
        ))}
      </datalist>
    </>
  );
}
