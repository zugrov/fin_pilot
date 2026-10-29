import { describe, expect, it } from "vitest";

import { formatMoney, fromCents, moneyToNumber, percentLabel, permille, toCents } from "./money";

describe("formatMoney", () => {
  it("группирует тысячи и ставит минус U+002D", () => {
    expect(formatMoney("27000.00")).toBe("27 000,00 ₽");
    expect(formatMoney("-19500.5")).toBe("-19 500,50 ₽");
  });

  it("null и мусор — «Нет данных», не ноль", () => {
    expect(formatMoney(null)).toBe("Нет данных");
    expect(formatMoney("")).toBe("Нет данных");
    expect(formatMoney("abc")).toBe("Нет данных");
  });
});

describe("toCents/fromCents", () => {
  it("копейки через BigInt", () => {
    expect(toCents("0.01")).toBe(1n);
    expect(fromCents(4750600n)).toBe("47506.00");
    expect(fromCents(-200000n)).toBe("-2000.00");
  });
});

describe("moneyToNumber", () => {
  it("строка в число для масштаба диаграммы", () => {
    expect(moneyToNumber("27000.00")).toBe(27000);
    expect(moneyToNumber("0.1")).toBeCloseTo(0.1);
    expect(moneyToNumber(null)).toBeNull();
    expect(moneyToNumber("мусор")).toBeNull();
  });
});

describe("permille и percentLabel: доли без float", () => {
  it("доля в промилле", () => {
    expect(permille(2500n, 10000n)).toBe(250n);
    expect(permille(1n, 3n)).toBe(333n); // округление вниз, без дробей
  });

  it("деление на ноль даёт 0, а не падение", () => {
    expect(permille(100n, 0n)).toBe(0n);
  });

  it("подпись процента: целое и с десятыми", () => {
    expect(percentLabel(250n)).toBe("25 %");
    expect(percentLabel(333n)).toBe("33,3 %");
    expect(percentLabel(0n)).toBe("0 %");
  });

  it("отрицательная доля с минусом U+2212", () => {
    expect(percentLabel(-500n)).toBe("−50 %");
  });
});
