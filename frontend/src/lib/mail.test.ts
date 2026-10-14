import { describe, expect, it } from "vitest";

import { coverageCaption, mailboxCaption, pollResultCaption, showsMailboxSecret } from "./mail";

describe("mailbox screen", () => {
  it("keeps an empty mailbox distinct from an error", () => {
    expect(mailboxCaption(null)).toBe("Почтового ящика нет");
    expect(mailboxCaption({ type: "file" })).toBe("Почтового ящика нет");
    expect(mailboxCaption({ type: "email" })).toBe("Почтовый ящик");
  });

  it("does not turn missing coverage into zero", () => {
    expect(coverageCaption(null)).toBe("Покрытие нет данных");
    expect(coverageCaption(null)).not.toContain("0.00");
    expect(coverageCaption("2026-10-13")).toBe("Покрытие 2026-10-13");
  });

  it("does not show a saved secret or a successful import", () => {
    expect(showsMailboxSecret({})).toBe(false);
    expect(showsMailboxSecret({ password: "secret" })).toBe(true);
    expect(pollResultCaption("Опрос почты выключен")).toBe("Опрос почты выключен");
    expect(pollResultCaption("Опрос почты выключен")).not.toContain("Импорт выполнен");
  });
});
