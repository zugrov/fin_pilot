import { describe, expect, it } from "vitest";

import {
  alertsPath,
  completenessCaption,
  recalculateAlertsPath,
  savedCalculationCaption,
} from "./alerts";

describe("чтение алертов", () => {
  it("не подставляет фиксированную дату", () => {
    const path = alertsPath("firm-a");
    expect(path).toBe("/api/v1/companies/firm-a/alerts");
    expect(path).not.toContain("2026-10-31");
    expect(path).not.toContain("report_date");
  });

  it("показывает дату сохранённого расчёта", () => {
    expect(savedCalculationCaption(null)).toBe("Сохранённого расчёта нет");
    expect(savedCalculationCaption("2026-10-16")).toBe("Последний расчёт на 2026-10-16");
  });

  it("не называет старый расчёт полным", () => {
    expect(completenessCaption("unknown")).toBe(
      "Полнота не определена для сохранённого расчёта",
    );
    expect(completenessCaption("unknown")).not.toContain("полные");
    expect(completenessCaption("known")).toBe("");
  });

  it("выносит пересчёт в отдельный запрос", () => {
    expect(recalculateAlertsPath("firm-a")).toBe("/api/v1/companies/firm-a/alerts/recalculate");
  });
});
