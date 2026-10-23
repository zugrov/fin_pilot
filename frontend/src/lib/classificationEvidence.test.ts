import { describe, expect, it } from "vitest";

import { classificationEvidenceLabel } from "./classificationEvidence";

describe("classificationEvidenceLabel", () => {
  it("legacy unknown only for rule origin without id", () => {
    expect(
      classificationEvidenceLabel("rule", { status: "legacy_unknown" }),
    ).toBe("Правило не зафиксировано (данные до обновления)");
  });

  it("manual label", () => {
    expect(classificationEvidenceLabel("manual", { status: "manual" })).toBe("Вручную");
  });

  it("recorded rule has no extra label", () => {
    expect(
      classificationEvidenceLabel("rule", {
        status: "recorded",
        rule_id: "00000000-0000-4000-8000-000000000001",
        rule_version: 1,
      }),
    ).toBeNull();
  });
});
