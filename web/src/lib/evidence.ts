export function evidenceRefs(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((v) => evidenceScalar(v)).filter(Boolean);
  }
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).map(
      ([k, v]) => `${k}: ${evidenceScalar(v)}`,
    );
  }
  const scalar = evidenceScalar(value);
  return scalar ? [scalar] : [];
}

function evidenceScalar(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
