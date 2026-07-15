import type { GovernanceFileGrant } from "@/lib/api";

export type GatewayPersonDraft = {
  user_id: string;
  name: string;
  roles: string[];
  teams: string[];
  governed: boolean;
  file_access: GovernanceFileGrant[];
};

export function normalizeGatewayPersonId(platformId: string, value: string): string {
  let normalized = value.trim().replace(/^["']|["']$/g, "").trim();
  const prefix = `${platformId}:`;
  if (normalized.toLowerCase().startsWith(prefix)) {
    normalized = normalized.slice(prefix.length).trim();
  }
  if (platformId === "discord") {
    const mention = normalized.match(/^<@!?(\d+)>$/);
    if (mention) return mention[1];
    return /^\d+$/.test(normalized) ? normalized : "";
  }
  return normalized && !normalized.includes(",") && !/\s/.test(normalized)
    ? normalized
    : "";
}
