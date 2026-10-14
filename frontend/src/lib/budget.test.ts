import { describe, expect, it } from "vitest";

import { alertEmpty, planFactText } from "./budget";

describe("planFactText", () => {
  it("does not turn a missing budget into zero", () => {
    expect(planFactText("unavailable", null, null)).toBe("Нет данных о плане-факте");
    expect(planFactText("unavailable", null, null)).not.toContain("0.00");
  });

  it("keeps a zero plan with a real fact outside the budget", () => {
    expect(planFactText("вне бюджета", "10000.00", null)).toBe("вне бюджета");
  });
});

describe("alertEmpty", () => {
  it("does not claim there are no risks", () => {
    expect(alertEmpty("preliminary", 0)).toBe("Нет данных для уверенного вывода");
    expect(alertEmpty("ready", 0)).not.toContain("рисков нет");
  });
});
