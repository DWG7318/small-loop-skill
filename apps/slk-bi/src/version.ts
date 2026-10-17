export const BI_VERSION = "1.1.4" as const;
export const COMPATIBLE_BI_VERSIONS = ["1.1.0", "1.1.1", "1.1.2", "1.1.3", BI_VERSION] as const;
export type BiVersion = typeof COMPATIBLE_BI_VERSIONS[number];
export function isCompatibleBiVersion(value: unknown): value is BiVersion {
  return COMPATIBLE_BI_VERSIONS.some((version) => version === value);
}
