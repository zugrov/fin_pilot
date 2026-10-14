import { describe, expect, it } from "vitest";

import { revenueDisplay } from "./revenue";

describe("выручка на экране", () => {
  it("не подставляет поступления, когда данных нет", () => {
    expect(revenueDisplay(null, "Нет данных о выручке")).toBe("Нет данных о выручке");
    expect(revenueDisplay(null, "Нет данных о выручке")).not.toBe("60000.00");
  });

  it("показывает ноль как выручку", () => {
    expect(revenueDisplay("0.00", "Выручка без НДС")).toBe("Выручка без НДС: 0.00");
  });
});
