import { describe, expect, it } from "vitest";

import {
  VAT_THRESHOLD_DISCLAIMER,
  vatThresholdApproachingText,
  vatThresholdExceededText,
  vatThresholdPartialNote,
  shouldShowVatThresholdBanner,
} from "./vatThreshold";

const block = {
  status: "approaching" as const,
  ytd_revenue: "16500000.00",
  threshold: "20000000.00",
  percent: "82.50",
  as_of: "2026-10-31",
  exceeded_month: null,
  obligation_from: null,
  partial: false,
  disclaimer: "usn_accrual_vs_cash",
};

describe("vatThreshold тексты", () => {
  it("строит текст при приближении к порогу", () => {
    const text = vatThresholdApproachingText(block);
    expect(text).toContain("16 500 000,00");
    expect(text).toContain("20 000 000,00");
    expect(text).toContain("следующего месяца");
    expect(text).toContain("на 31.10.2026");
  });

  it("строит текст при превышении", () => {
    const exceeded = {
      ...block,
      status: "exceeded" as const,
      exceeded_month: "2026-10",
      obligation_from: "2026-11-01",
    };
    const text = vatThresholdExceededText(exceeded);
    expect(text).toContain("Порог превышен");
    expect(text).toContain("01.11.2026");
    expect(text).toContain("создайте версию");
    expect(text).toContain("на 31.10.2026");
  });

  it("показывает баннер только для approaching и exceeded", () => {
    expect(shouldShowVatThresholdBanner(block)).toBe(true);
    expect(shouldShowVatThresholdBanner({ ...block, status: "ok" })).toBe(false);
    expect(shouldShowVatThresholdBanner(null)).toBe(false);
  });

  it("даёт дисклеймер и пометку неполных данных", () => {
    expect(VAT_THRESHOLD_DISCLAIMER).toContain("поступлениям");
    expect(vatThresholdPartialNote(true)).toContain("неполные");
    expect(vatThresholdPartialNote(false)).toBeNull();
  });
});
