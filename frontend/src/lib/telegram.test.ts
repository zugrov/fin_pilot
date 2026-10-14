import { describe, expect, it } from "vitest";

import { bindingCaption, canPreview, tokenNotice } from "./telegram";

describe("telegram screen", () => {
  it("previews only an active binding", () => {
    expect(canPreview("active")).toBe(true);
    expect(canPreview("pending")).toBe(false);
    expect(canPreview("none")).toBe(false);
    expect(canPreview("revoked")).toBe(false);
  });

  it("keeps the token screen free of financial claims", () => {
    expect(tokenNotice()).toBe("Токен не содержит финансовых данных.");
    expect(tokenNotice()).not.toContain("рисков нет");
    expect(bindingCaption("none")).toBe("нет привязки");
  });
});
