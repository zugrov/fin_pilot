import { describe, expect, it } from "vitest";

import { gapDisplay } from "./forecast";

describe("gapDisplay", () => {
  it("does not replace a missing forecast with zero", () => {
    expect(gapDisplay(null, "preliminary")).toBe("Нет данных о прогнозе");
    expect(gapDisplay(null, "preliminary")).not.toContain("0.00");
  });

  it("shows a real shortfall", () => {
    expect(gapDisplay("30000.00", "ready")).toBe("Дефицит: 30000.00");
  });
});
