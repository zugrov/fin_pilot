export type ClassificationEvidence =
  | { status: "recorded"; rule_id: string; rule_version: number }
  | { status: "legacy_unknown" }
  | { status: "manual" }
  | null
  | undefined;

export function classificationEvidenceLabel(
  origin: string | undefined,
  evidence: ClassificationEvidence,
): string | null {
  if (origin === "manual" || evidence?.status === "manual") {
    return "Вручную";
  }
  if (origin === "rule" && evidence?.status === "legacy_unknown") {
    return "Правило не зафиксировано (данные до обновления)";
  }
  if (origin === "rule" && evidence?.status === "recorded") {
    return null;
  }
  return null;
}
