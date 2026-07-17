import type {
  GovernanceApprovalUser,
  GovernanceFileGrant,
} from "@/lib/api";

function roleSatisfies(
  grantedRole: string,
  requiredRole: string,
  hierarchy: string[],
): boolean {
  if (grantedRole === requiredRole) return true;
  const grantedIndex = hierarchy.indexOf(grantedRole);
  const requiredIndex = hierarchy.indexOf(requiredRole);
  return (
    grantedIndex >= 0 &&
    requiredIndex >= 0 &&
    grantedIndex >= requiredIndex
  );
}

export function isFileApprovalUser(
  user: Pick<GovernanceApprovalUser, "roles">,
  hierarchy: string[],
): boolean {
  return user.roles.some((role) =>
    roleSatisfies(role, "manager", hierarchy),
  );
}

export function selectedFileApproverKeys(
  grant: Pick<
    GovernanceFileGrant,
    "write_approval_roles" | "write_approval_users"
  >,
  users: GovernanceApprovalUser[],
  hierarchy: string[],
): string[] {
  const selected = new Set(grant.write_approval_users ?? []);
  const legacyRoles = grant.write_approval_roles ?? [];
  if (legacyRoles.length > 0) {
    for (const user of users) {
      if (
        user.roles.some((grantedRole) =>
          legacyRoles.some((requiredRole) =>
            roleSatisfies(grantedRole, requiredRole, hierarchy),
          ),
        )
      ) {
        selected.add(user.actor_key);
      }
    }
  }
  return [...selected];
}

export function validateGovernanceFileGrants(
  grants: GovernanceFileGrant[],
  users: GovernanceApprovalUser[],
  hierarchy: string[],
): string | null {
  const userByKey = new Map(users.map((user) => [user.actor_key, user]));
  for (const grant of grants) {
    if (!grant.path.trim()) return "Every file access grant needs a path.";
    const requiresApproval =
      grant.write_requires_approval === true ||
      (grant.write_approval_roles?.length ?? 0) > 0 ||
      (grant.write_approval_users?.length ?? 0) > 0;
    if (!requiresApproval) continue;
    if (!grant.write) {
      return `Write approval for ${grant.path} requires write access.`;
    }
    const selected = selectedFileApproverKeys(grant, users, hierarchy);
    if (selected.length === 0) {
      return `Select at least one manager or administrator to approve writes for ${grant.path}.`;
    }
    const invalid = selected.filter((actorKey) => {
      const user = userByKey.get(actorKey);
      return !user || !isFileApprovalUser(user, hierarchy);
    });
    if (invalid.length > 0) {
      return `Selected write approvers are no longer eligible: ${invalid.join(", ")}.`;
    }
  }
  return null;
}
