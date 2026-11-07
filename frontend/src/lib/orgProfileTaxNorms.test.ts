import { describe, expect, it } from "vitest";

import { formatThresholdLine, priorYearBandLabels } from "./orgProfileTaxNorms";

describe("orgProfileTaxNorms", () => {
  it("подписи диапазонов выручки", () => {
    const labels = priorYearBandLabels({
      usn_vat_exemption_threshold_rub: "20000000.00",
      computed_special_cap_5_rub: "272500000.00",
      computed_special_cap_7_rub: "490500000.00",
    });
    expect(labels.under_exemption_threshold).toContain("20");
    expect(labels.from_threshold_to_cap_5).toContain("272");
    expect(labels.over_cap_7).toContain("490");
  });

  it("строка порога", () => {
    const line = formatThresholdLine({ usn_vat_exemption_threshold_rub: "20000000.00" });
    expect(line).toContain("20");
    expect(line).toContain("справочнику");
  });
});
