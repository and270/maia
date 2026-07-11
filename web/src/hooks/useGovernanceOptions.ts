import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/** Fetch the configured governance role and team vocabulary once for a page. */
export function useGovernanceOptions(): { roles: string[]; teams: string[] } {
  const [roles, setRoles] = useState<string[]>([]);
  const [teams, setTeams] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .getGovernanceOptions()
      .then((response) => {
        if (cancelled) return;
        setRoles(response.roles ?? []);
        setTeams(response.teams ?? []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return { roles, teams };
}
