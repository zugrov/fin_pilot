import { describe, expect, it } from "vitest";

import { mapVatQuestionToSnapshot, snapshotToVatQuestion, step3FieldVisibility } from "./orgProfileVat";

describe("orgProfileVat", () => {
  it("маппит ответ «Вы платите НДС?»", () => {
    const mapped = mapVatQuestionToSnapshot("usn_special", { taxSystem: "usn" });
    expect(mapped.vat_status).toBe("special_rates_5_7");
    expect(mapped.vat_regime_detail).toBe("special_without_deductions");
  });

  it("восстанавливает вопрос из снимка", () => {
    expect(snapshotToVatQuestion({ vat_status: "not_applicable" })).toBe("not_applicable");
  });

  it("видимость полей шага 3", () => {
    const vis = step3FieldVisibility({
      tax_system: "usn",
      vat_status: "vat_payer",
      is_new_organization: true,
    });
    expect(vis.showUsnObject).toBe(true);
    expect(vis.showVatRate).toBe(true);
    expect(vis.showRevenueBand).toBe(false);
    expect(vis.showArticle145).toBe(false);
  });
});
