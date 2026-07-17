import { useEffect, useState } from "react";
import { api, type GovernanceApprovalUser } from "@/lib/api";

/** Fetch the configured governance role and team vocabulary once for a page. */
export function useGovernanceOptions(): {
  roles: string[];
  teams: string[];
  approvalUsers: GovernanceApprovalUser[];
} {
  const [roles, setRoles] = useState<string[]>([]);
  const [teams, setTeams] = useState<string[]>([]);
  const [approvalUsers, setApprovalUsers] = useState<GovernanceApprovalUser[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .getGovernanceOptions()
      .then((response) => {
        if (cancelled) return;
        setRoles(response.roles ?? []);
        setTeams(response.teams ?? []);
        setApprovalUsers(response.approval_users ?? []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return { roles, teams, approvalUsers };
}
