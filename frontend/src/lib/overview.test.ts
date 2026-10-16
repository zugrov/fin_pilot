import { describe, expect, it } from "vitest";

import { balanceLabel, cashAmount, flowLabel, qualityNotes } from "./overview";

describe("показатели обзора", () => {
  it("не подменяет отсутствие данных нулём и не берёт остаток", () => {
    expect(cashAmount(null, "Нет данных")).toBe("Нет данных");
    expect(cashAmount(null, "Нет данных")).not.toBe("0.00");
    expect(cashAmount("15000.00", "Нет данных")).toBe("15000.00");
    expect(cashAmount("108499.50", "Нет остатка")).not.toBe("15000.00");
  });

  it("показывает предупреждения о качестве", () => {
    const notes = qualityNotes([
      "unclassified_operations",
      "intraday_approximation",
      "missing_opening_balance",
    ]);
    expect(notes[0]).toContain("без категории");
    expect(notes[1]).toContain("конец дня");
    expect(notes[2]).toContain("по загруженным операциям");
  });

  it("подписывает период оборотов и момент остатка", () => {
    expect(flowLabel("Поступления", "2026-10-01", "2026-10-31", false)).toBe(
      "Поступления за 2026-10-01 — 2026-10-31",
    );
    expect(flowLabel("Выплаты", "2026-10-01", "2026-10-31", true)).toContain(
      "по загруженным операциям",
    );
    const label = balanceLabel("2026-10-16T09:00:00+00:00");
    expect(label).toContain("16.10.2026");
    expect(label).toContain("12:00");
  });
});
