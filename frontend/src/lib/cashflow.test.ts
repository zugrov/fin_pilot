import { describe, expect, it } from "vitest";

import {
  cashflowErrorText,
  completenessLabel,
  completenessNote,
  DRILLDOWN_LIMIT,
  drilldownNotice,
  emptyStateText,
  flagNotes,
  formatMoney,
  fromCents,
  hasUnclassified,
  isDrilldownTruncated,
  isUnavailable,
  MISSING_VALUE,
  netOf,
  sectionHint,
  sectionLabel,
  sectionNetText,
  sumMoney,
  toCents,
  totalsMismatch,
} from "./cashflow";

describe("formatMoney", () => {
  it("форматирует рубли с пробелами и запятой", () => {
    expect(formatMoney("27000.00")).toBe("27 000,00 ₽");
    expect(formatMoney("46500.50")).toBe("46 500,50 ₽");
    expect(formatMoney("117500.00")).toBe("117 500,00 ₽");
    expect(formatMoney("1000000.00")).toBe("1 000 000,00 ₽");
    expect(formatMoney("999.99")).toBe("999,99 ₽");
    expect(formatMoney("0.00")).toBe("0,00 ₽");
  });

  it("сохраняет отрицательные суммы", () => {
    expect(formatMoney("-19500.50")).toBe("\u221219 500,50 ₽");
    expect(formatMoney("-0.00")).toBe("0,00 ₽");
  });

  it("не показывает нуль вместо отсутствующих данных", () => {
    expect(formatMoney(null)).toBe(MISSING_VALUE);
    expect(formatMoney(undefined)).toBe(MISSING_VALUE);
    expect(formatMoney("")).toBe(MISSING_VALUE);
    expect(formatMoney("не число")).toBe(MISSING_VALUE);
    expect(formatMoney(null, "Нет остатка")).toBe("Нет остатка");
  });

  it("дополняет копейки до двух знаков без float", () => {
    expect(formatMoney("7.5")).toBe("7,50 ₽");
    expect(formatMoney("7.567")).toBe("7,56 ₽");
    expect(formatMoney("1234567.891")).toBe("1 234 567,89 ₽");
  });
});

describe("денежная арифметика на строках", () => {
  it("переводит строку в копейки", () => {
    expect(toCents("27000.00")).toBe(2700000n);
    expect(toCents("-19500.50")).toBe(-1950050n);
    expect(toCents("мусор")).toBeNull();
  });

  it("возвращает строку из копеек", () => {
    expect(fromCents(2700000n)).toBe("27000.00");
    expect(fromCents(-1950050n)).toBe("-19500.50");
    expect(fromCents(5n)).toBe("0.05");
  });

  it("суммирует без потери копеек", () => {
    expect(sumMoney(["12000.00", "15000.00"])).toBe("27000.00");
    expect(sumMoney(["0.50", "1.50"])).toBe("2.00");
    expect(sumMoney(["0.10", "0.20"])).toBe("0.30");
    expect(sumMoney([])).toBe("0.00");
  });

  it("возвращает null, если есть неденежное значение", () => {
    expect(sumMoney(["10.00", null])).toBeNull();
    expect(sumMoney(["10.00", "abc"])).toBeNull();
  });

  it("считает итог секции", () => {
    expect(netOf("20000.00", "3000.00")).toBe("17000.00");
    expect(netOf("4800.00", "0.00")).toBe("4800.00");
    expect(sectionNetText("0.00", "150.00")).toBe("\u2212150,00 ₽");
    expect(sectionNetText("5000.00", "1200.00")).toBe("3 800,00 ₽");
  });

  it("не выдаёт 0,00 при отсутствии значений", () => {
    expect(sectionNetText("", "150.00")).toBe(MISSING_VALUE);
    expect(sectionNetText("0.00", "")).toBe(MISSING_VALUE);
  });
});

describe("метки секций", () => {
  it("переводит все коды секций на понятный язык", () => {
    expect(sectionLabel("operating")).toBe("Операционная деятельность");
    expect(sectionLabel("investing")).toBe("Инвестиционная деятельность");
    expect(sectionLabel("financing")).toBe("Финансовая деятельность");
    expect(sectionLabel("technical")).toBe("Технические операции");
    expect(sectionLabel("unmapped")).toBe("Не разнесено по видам деятельности");
  });

  it("даёт подсказки для technical и unmapped", () => {
    expect(sectionHint("technical")).toContain("между своими счетами");
    expect(sectionHint("unmapped")).toContain("без категории");
    expect(sectionHint("operating")).toBeNull();
  });

  it("не теряет неизвестный код", () => {
    expect(sectionLabel("unknown")).toBe("unknown");
  });
});

describe("состояния полноты", () => {
  it("переводит статусы", () => {
    expect(completenessLabel("unavailable")).toBe("Нет данных");
    expect(completenessLabel("preliminary")).toBe("Предварительно");
    expect(completenessLabel("full")).toBe("Полно");
    expect(completenessLabel(null)).toBe(MISSING_VALUE);
    expect(completenessLabel("что-то")).toBe(MISSING_VALUE);
  });

  it("объясняет статусы простыми словами", () => {
    expect(completenessNote("unavailable")).toContain("не загружено");
    expect(completenessNote("preliminary")).toContain("неполные");
    expect(completenessNote("full")).toContain("Все операции");
  });

  it("распознаёт отсутствие данных", () => {
    expect(isUnavailable("unavailable")).toBe(true);
    expect(isUnavailable("full")).toBe(false);
    expect(isUnavailable(null)).toBe(false);
  });
});

describe("метки quality_flags", () => {
  it("переводит известные флаги", () => {
    const notes = flagNotes(["unclassified_operations", "partial_period"]);
    expect(notes[0]).toContain("без категории");
    expect(notes[1]).toContain("не весь период");
  });

  it("не скрывает неизвестный флаг", () => {
    expect(flagNotes(["new_flag"])).toEqual(["new_flag"]);
  });

  it("находит флаг неразнесённых операций", () => {
    expect(hasUnclassified(["unclassified_operations"])).toBe(true);
    expect(hasUnclassified(["partial_period"])).toBe(false);
    expect(hasUnclassified([])).toBe(false);
  });
});

describe("drill-down", () => {
  it("предупреждает при достижении лимита", () => {
    const ids = Array.from({ length: DRILLDOWN_LIMIT }, (_, index) => `id-${index}`);
    expect(isDrilldownTruncated(ids)).toBe(true);
    expect(isDrilldownTruncated(ids.slice(0, 5))).toBe(false);
    expect(isDrilldownTruncated(undefined)).toBe(false);
    expect(drilldownNotice()).toContain("первые 100");
  });

  it("объясняет пустое состояние", () => {
    expect(emptyStateText()).toContain("Загрузите выписку");
  });
});

describe("ошибки по HTTP-статусу", () => {
  it("различает 403, 404, 422 и 402", () => {
    expect(cashflowErrorText({ status: 403 })).toContain("Нет доступа");
    expect(cashflowErrorText({ status: 404 })).toContain("не найдена");
    expect(cashflowErrorText({ status: 422 })).toContain("даты периода");
    expect(cashflowErrorText({ status: 402 })).toContain("тариф");
  });

  it("для сети даёт понятный текст", () => {
    expect(cashflowErrorText(new Error("Failed to fetch"))).toContain("Не удалось загрузить");
    expect(cashflowErrorText(null)).toContain("Не удалось загрузить");
  });

  it("показывает серверное сообщение при прочих статусах", () => {
    expect(cashflowErrorText({ status: 500, message: "Внутренняя ошибка" })).toBe(
      "Внутренняя ошибка",
    );
  });
});

describe("сверка итога", () => {
  it("совпадает с суммой секций", () => {
    // operating 5000/1200, investing 0/800, financing 10000/0, technical 0/150, unmapped 300/0
    expect(totalsMismatch("13150.00", ["3800.00", "-800.00", "10000.00", "-150.00", "300.00"])).toBe(
      false,
    );
    expect(totalsMismatch("17000.00", ["17000.00", "0.00", "0.00", "0.00", "0.00"])).toBe(false);
  });

  it("сигнализирует расхождение", () => {
    expect(totalsMismatch("100.00", ["50.00", "0.00", "0.00", "0.00", "0.00"])).toBe(true);
  });

  it("молчит, если данных нет", () => {
    expect(totalsMismatch("100.00", [null, "0.00"])).toBe(false);
  });
});
