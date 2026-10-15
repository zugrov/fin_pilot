import { describe, expect, it } from "vitest";

import { monthPayLabel, renewPayLabel, yearPayLabel } from "./cta";

describe("подписи оплаты берут сумму сервера", () => {
  it("год", () => {
    expect(yearPayLabel("25500.00")).toBe("Оплатить год — 25500 ₽");
    expect(yearPayLabel("40800.00")).toBe("Оплатить год — 40800 ₽");
    expect(yearPayLabel("56100.00")).toBe("Оплатить год — 56100 ₽");
    expect(yearPayLabel("86700.00")).toBe("Оплатить год — 86700 ₽");
  });

  it("месяц", () => {
    expect(monthPayLabel("2500.00")).toBe("Оплатить месяц — 2500 ₽");
    expect(monthPayLabel("8500.00")).toBe("Оплатить месяц — 8500 ₽");
  });

  it("продление не подменяет цену", () => {
    expect(renewPayLabel("2500.00", "month")).toBe("Продлить подписку на месяц — 2500 ₽");
    expect(renewPayLabel("25500.00", "year")).toBe("Продлить подписку на год — 25500 ₽");
  });

  it("не считает скидку на клиенте", () => {
    expect(yearPayLabel("25500.00")).not.toContain("21675");
  });
});
