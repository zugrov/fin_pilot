import { describe, expect, it } from "vitest";

import { formatDate, formatDateRange } from "./dates";

describe("formatDate", () => {
  it("ISO из API → читаемый вид, значение не теряется", () => {
    expect(formatDate("2026-10-31")).toBe("31.10.2026");
    expect(formatDate("2026-01-05")).toBe("05.01.2026");
    // Значение осталось тем же, но отображение другое.
    expect(formatDate("2026-10-31")).not.toBe("2026-10-31");
  });

  it("пустое значение — «Нет данных», а не пустая строка", () => {
    expect(formatDate(null)).toBe("Нет данных");
    expect(formatDate(undefined)).toBe("Нет данных");
    expect(formatDate("")).toBe("Нет данных");
  });

  it("неузнанную строку отдаёт как есть, чтобы не терять данные", () => {
    expect(formatDate("2026-10-31T12:00:00Z")).toBe("2026-10-31T12:00:00Z");
    expect(formatDate("вчера")).toBe("вчера");
  });
});

describe("formatDateRange", () => {
  it("диапазон без ISO-остатков", () => {
    expect(formatDateRange("2026-10-01", "2026-10-31")).toBe("01.10.2026 — 31.10.2026");
  });
});
