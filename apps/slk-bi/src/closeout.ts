import type { CloseoutSummary, DeviceSignature } from "./contracts";

export function deviceSignatureLabel(value?: DeviceSignature) {
  return [value?.computer_name, value?.ip_address, value?.os_version].map((part) => part?.trim() || "未获取").join(" · ");
}

export function canonicalSummary(value: CloseoutSummary) {
  return JSON.stringify({ body: value.body, authored_by: value.authored_by, recorded_at: value.recorded_at,
    source_id: value.source_id, source_revision: value.source_revision });
}

export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, v]) => `${JSON.stringify(key)}:${canonicalJson(v)}`).join(",")}}`;
  return JSON.stringify(value);
}

export async function sha256(value: string) {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, "0")).join("");
}
