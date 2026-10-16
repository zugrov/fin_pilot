import { describe, expect, it } from "vitest";

import {
  closingLabel,
  companyDate,
  forecastCaption,
  forecastErrorText,
  forecastPath,
  gapDisplay,
  matchesSelection,
  unpaidLabel,
} from "./forecast";

describe("дата прогноза", () => {
  it("берёт календарный день фирмы, а не UTC", () => {
    const late = new Date("2026-10-16T21:30:00Z");
    expect(companyDate("Europe/Moscow", late)).toBe("2026-10-17");
    expect(companyDate("Europe/Moscow", late)).not.toBe(late.toISOString().slice(0, 10));
    const morning = new Date("2026-10-16T06:00:00Z");
    expect(companyDate("America/Los_Angeles", morning)).toBe("2026-10-15");
  });

  it("не подменяет явно заданный часовой пояс", () => {
    const late = new Date("2026-10-16T21:30:00Z");
    expect(companyDate("America/Los_Angeles", late)).toBe("2026-10-16");
    expect(companyDate("America/Los_Angeles", late)).not.toBe(companyDate("Europe/Moscow", late));
    expect(companyDate("", late)).toBe(companyDate("Europe/Moscow", late));
  });

  it("меняет дату в запросе", () => {
    const first = forecastPath("firm-a", "2026-10-16", "base");
    const second = forecastPath("firm-a", "2026-10-20", "base");
    expect(first).toContain("as_of=2026-10-16");
    expect(second).toContain("as_of=2026-10-20");
    expect(first).not.toBe(second);
    expect(first).not.toContain("2026-10-14");
  });

  it("меняет фирму в запросе", () => {
    const first = forecastPath("firm-a", "2026-10-16", "base");
    const second = forecastPath("firm-b", "2026-10-16", "base");
    expect(first).toContain("/companies/firm-a/");
    expect(second).toContain("/companies/firm-b/");
    expect(first).not.toBe(second);
  });

  it("не принимает пустой ответ за расчёт выбранной фирмы", () => {
    expect(matchesSelection(undefined, undefined, "2026-10-16")).toBe(false);
    expect(
      matchesSelection(
        { company_id: "firm-a", as_of: "2026-10-16" },
        "firm-a",
        "2026-10-20",
      ),
    ).toBe(false);
    expect(
      matchesSelection(
        { company_id: "firm-a", as_of: "2026-10-16" },
        "firm-a",
        "2026-10-16",
      ),
    ).toBe(true);
  });

  it("совпадает с подписью на экране", () => {
    const asOf = "2026-10-16";
    const path = forecastPath("firm-a", asOf, "base");
    expect(path).toContain(`as_of=${asOf}`);
    expect(forecastCaption(asOf)).toBe(`Расчёт на ${asOf}`);
    expect(forecastCaption(asOf)).toContain(asOf);
  });
});

describe("показатели прогноза", () => {
  it("показывает отрицательный остаток и положительный дефицит", () => {
    expect(closingLabel("2026-10-20", "-29500.50")).toBe(
      "Прогнозный остаток на 2026-10-20: -29500.50",
    );
    expect(gapDisplay("29500.50", "ready")).toBe("Дефицит: 29500.50");
    expect(unpaidLabel("110000.00", "2026-10-20")).toBe(
      "Неоплаченная выплата 110000.00 на 2026-10-20",
    );
  });

  it("не подменяет ошибку нулевым дефицитом", () => {
    expect(gapDisplay(null, "preliminary")).toBe("Нет данных о прогнозе");
    expect(gapDisplay(null, "preliminary")).not.toContain("0.00");
    expect(forecastErrorText()).toBe("Не удалось посчитать прогноз.");
    expect(forecastErrorText()).not.toContain("0.00");
  });
});
