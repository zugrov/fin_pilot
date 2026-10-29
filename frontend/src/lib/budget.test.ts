import { describe, expect, it } from "vitest";

import {
  alertEmpty,
  amountText,
  basisLabel,
  calculationCaption,
  cashBudgetNote,
  defaultReportDate,
  draftDisabledReason,
  futureFactNote,
  interimNote,
  matchesPlanFact,
  monthEnd,
  monthLabel,
  planFactPath,
  planFactText,
  salesFactNote,
  versionStatusLabel,
} from "./budget";

describe("planFactText", () => {
  it("does not turn a missing budget into zero", () => {
    expect(planFactText("unavailable", null, null)).toBe("Нет данных о плане-факте");
    expect(planFactText("unavailable", null, null)).not.toContain("0.00");
  });

  it("keeps a zero plan with a real fact outside the budget", () => {
    expect(planFactText("вне бюджета", "10000.00", null)).toBe("вне бюджета");
  });
});

describe("дата среза бюджета", () => {
  it("берёт календарный день фирмы и подставляет его в запрос", () => {
    const late = new Date("2026-10-16T21:30:00Z");
    const moscow = defaultReportDate("Europe/Moscow", late);
    expect(moscow).toBe("2026-10-17");
    expect(moscow).not.toBe(late.toISOString().slice(0, 10));
    const path = planFactPath("firm-a", moscow);
    expect(path).toContain("report_date=2026-10-17");
    expect(path).not.toContain("2026-10-31");
    expect(defaultReportDate("America/Los_Angeles", late)).toBe("2026-10-16");
    expect(defaultReportDate("", late)).toBe(defaultReportDate("Europe/Moscow", late));
  });

  it("меняет фирму и дату в запросе", () => {
    const first = planFactPath("firm-a", "2026-10-16");
    const otherDay = planFactPath("firm-a", "2026-10-20");
    const otherFirm = planFactPath("firm-b", "2026-10-16");
    expect(first).not.toBe(otherDay);
    expect(first).not.toBe(otherFirm);
    expect(matchesPlanFact(undefined, undefined, "2026-10-16")).toBe(false);
    expect(
      matchesPlanFact(
        { company_id: "firm-a", report_date: "2026-10-16" },
        "firm-b",
        "2026-10-16",
      ),
    ).toBe(false);
    expect(
      matchesPlanFact(
        { company_id: "firm-a", report_date: "2026-10-16" },
        "firm-a",
        "2026-10-20",
      ),
    ).toBe(false);
  });
});

describe("показатели бюджета", () => {
  it("различает план месяца и план на дату", () => {
    expect(monthEnd(2026, 10)).toBe("2026-10-31");
    expect(monthLabel(2026, 10)).toBe("2026-10");
    expect(basisLabel("revenue")).toBe("Выручка без НДС");
    expect(basisLabel("revenue")).not.toContain("Поступления");
    expect(versionStatusLabel("approved")).toBe("утверждён");
    expect(amountText("25000.00")).toBe("25 000,00 ₽");
    expect(amountText("12903.20")).toBe("12 903,20 ₽");
    expect(amountText("25000.00")).not.toBe(amountText("12903.20"));
    expect(amountText("7096.80")).toBe("7 096,80 ₽");
    expect(amountText("55.00")).toBe("55,00 ₽");
    expect(calculationCaption("2026-10-16")).toBe("Расчёт на 16.10.2026");
  });

  it("не заменяет отсутствие данных нулём", () => {
    expect(amountText(null)).toBe("—");
    expect(amountText(undefined)).not.toContain("0.00");
    expect(monthLabel(null, 10)).toBe("—");
  });

  it("оставляет строку выручки видимой без денежного бюджета", () => {
    const bases = [
      { basis: "cash", status: "unavailable", lines: [] as { fact: string }[] },
      { basis: "revenue", status: "ready", lines: [{ fact: "20000.00" }] },
    ];
    const revenue = bases.find((item) => item.basis === "revenue");
    expect(cashBudgetNote(bases[0].status)).toBe("Денежный бюджет не задан");
    expect(revenue?.lines).toHaveLength(1);
    expect(revenue?.lines[0].fact).toBe("20000.00");
  });

  it("не считает неподтверждённую полноту окончательным фактом", () => {
    const note = salesFactNote("unknown");
    expect(note).toBe("Факт по загруженным продажам. Полнота данных не подтверждена.");
    expect(salesFactNote(undefined)).toBe(note);
    expect(note).not.toContain("полные");
    expect(salesFactNote("known")).toBe("");
    const interim = interimNote("2026-10-16", "2026-10-16", "2026-10-31");
    expect(interim).toBe("Промежуточный срез, не итог месяца.");
    expect(interimNote("2026-10-16", "2026-10-31", "2026-10-31")).toBe(interim);
    expect(interimNote("2026-11-02", "2026-10-31", "2026-10-31")).toBe("");
    const future = futureFactNote("2026-10-16", "2026-10-31");
    expect(future).toContain("не являются итогом");
    expect(futureFactNote("2026-10-16", "2026-10-16")).toBe("");
  });

  it("не предлагает скрытое создание расхода", () => {
    expect(draftDisabledReason()).toContain("отключено");
    expect(draftDisabledReason()).not.toContain("cash_out");
  });
});

describe("alertEmpty", () => {
  it("does not claim there are no risks", () => {
    expect(alertEmpty("preliminary", 0)).toBe("Нет данных для уверенного вывода");
    expect(alertEmpty("ready", 0)).not.toContain("рисков нет");
  });
});
