import { describe, expect, it } from "vitest";

import {
  buildStep3DraftPatch,
  mapVatQuestionToSnapshot,
  showUsnExemptionThresholdHint,
  snapshotToVatQuestion,
  step3FieldVisibility,
} from "./orgProfileVat";

describe("orgProfileVat", () => {
  it("exemption_145 для УСН ставит article_145 true", () => {
    const mapped = mapVatQuestionToSnapshot("exemption_145", { taxSystem: "usn" });
    expect(mapped.vat_status).toBe("exemption");
    expect(mapped.vat_exemption_article_145).toBe(true);
  });

  it("exemption_145 для ОСНО ставит article_145 true", () => {
    const mapped = mapVatQuestionToSnapshot("exemption_145", { taxSystem: "osno" });
    expect(mapped.vat_status).toBe("exemption");
    expect(mapped.vat_exemption_article_145).toBe(true);
  });

  it("Не знаю — null article_145", () => {
    const mapped = mapVatQuestionToSnapshot("unknown", { taxSystem: "usn" });
    expect(mapped.vat_exemption_article_145).toBeNull();
  });

  it("общий порядок — false article_145", () => {
    const mapped = mapVatQuestionToSnapshot("general_payer", { taxSystem: "osno" });
    expect(mapped.vat_exemption_article_145).toBe(false);
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
    expect(vis.showVatRate).toBe(true);
    expect(vis.showRevenueBand).toBe(false);
  });

  it("buildStep3DraftPatch без авто not_applicable", () => {
    const body = buildStep3DraftPatch({
      taxSystem: "usn",
      vatAnswer: "unknown",
      vatRate: "22",
      pricesIncludeVat: "unknown",
      isNewOrg: false,
      revenueBand: "under_exemption_threshold",
    });
    expect(body.vat_status).toBe("unknown");
    expect(body.prior_year_revenue_band).toBe("under_exemption_threshold");
  });

  it("подсказка порога УСН", () => {
    expect(
      showUsnExemptionThresholdHint({
        taxSystem: "usn",
        revenueBand: "under_exemption_threshold",
        vatAnswer: "unknown",
      }),
    ).toBe(true);
  });
});
