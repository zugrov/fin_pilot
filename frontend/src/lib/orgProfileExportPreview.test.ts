import { describe, expect, it } from "vitest";

import { buildExportPreviewLines } from "./orgProfileExportPreview";

describe("orgProfileExportPreview", () => {
  it("базовый набор при канале bank", () => {
    const lines = buildExportPreviewLines({ money_channels: ["bank"] });
    expect(lines.some((line) => line.title.includes("ClientBank"))).toBe(true);
    expect(lines.some((line) => line.title.includes("51"))).toBe(true);
  });

  it("добавляет эквайринг и НДС по условиям", () => {
    const lines = buildExportPreviewLines({
      money_channels: ["bank", "acquiring"],
      vat_status: "vat_payer",
      accounting_source: "onec",
      industry_sphere: "trade",
    });
    expect(lines.some((line) => line.title.includes("57.03"))).toBe(true);
    expect(lines.some((line) => line.title.includes("62"))).toBe(true);
    expect(lines.some((line) => line.title.includes("НДС"))).toBe(true);
  });

  it("расходы УСН при объекте доходы минус расходы", () => {
    const lines = buildExportPreviewLines({
      money_channels: ["bank"],
      usn_tax_object: "income_minus_expense",
    });
    expect(lines.some((line) => line.title.includes("УСН"))).toBe(true);
  });
});
