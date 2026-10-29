import { describe, expect, it } from "vitest";

import {
  applyOpeningAfterFailure,
  applyWalletCreateAfterFailure,
  balanceLabel,
  buildOpeningEffectiveAt,
  classifyWalletWriteFailure,
  completeOpeningAttempt,
  formFieldsMatchOpeningAttempt,
  guardCompanySwitch,
  lockedCompanyId,
  markOpeningSubmitExecuting,
  markWalletCreateUnknown,
  openingAttemptAfterCancel,
  openingSubmitPayloadKey,
  openingSummary,
  parseAmountInput,
  pendingOpeningFromAttempt,
  resolveOpeningConfirmAttempt,
  shouldRestoreOpeningFromAttempt,
  resolveWalletCreateSubmit,
  walletCreatePayloadKey,
} from "./walletForm";

const createPayload = {
  companyId: "c1",
  name: "Банк",
  type: "bank",
  code: "main",
};

const openingPayload = {
  companyId: "c1",
  walletId: "w1",
  amount: "100.00",
  effectiveAt: "2026-10-01T00:00:00+03:00",
};

const openingMeta = {
  walletLabel: "Банк (main)",
  offsetUsed: "+03:00",
  currency: "RUB",
};

describe("walletForm", () => {
  it("принимает сумму с копейками и ноль", () => {
    expect(parseAmountInput("0.00")).toEqual({ ok: true, value: "0.00" });
  });

  it("не показывает ноль вместо отсутствующего остатка", () => {
    expect(balanceLabel(null, ["missing_anchor"])).toBe("Нет начального остатка");
    expect(balanceLabel("0.00", [])).toBe("0,00 ₽");
  });

  it("сохраняет ключ create при том же payload после unknown", () => {
    const unknown = markWalletCreateUnknown({
      key: "key-a",
      payload: createPayload,
      phase: "executing",
    });
    const retry = resolveWalletCreateSubmit(unknown, createPayload, () => "key-b");
    expect(retry.kind).toBe("submit");
    if (retry.kind === "submit") {
      expect(retry.attempt.key).toBe("key-a");
      expect(retry.attempt.phase).toBe("executing");
    }
  });

  it("create timeout: изменение полей не подменяет unknown-попытку", () => {
    const unknown = markWalletCreateUnknown({
      key: "key-a",
      payload: createPayload,
      phase: "executing",
    });
    const blocked = resolveWalletCreateSubmit(
      unknown,
      { ...createPayload, code: "other" },
      () => "key-b",
    );
    expect(blocked.kind).toBe("blocked");
    if (blocked.kind === "blocked") {
      expect(blocked.attempt.key).toBe("key-a");
      expect(blocked.attempt.phase).toBe("unknown");
    }
  });

  it("выдаёт новый ключ create при изменении payload без блокировки", () => {
    const first = resolveWalletCreateSubmit(null, createPayload, () => "key-a");
    expect(first.kind).toBe("submit");
    const changed = resolveWalletCreateSubmit(
      null,
      { ...createPayload, code: "other" },
      () => "key-b",
    );
    expect(changed.kind).toBe("submit");
    if (changed.kind === "submit" && first.kind === "submit") {
      expect(changed.attempt.key).toBe("key-b");
      expect(walletCreatePayloadKey(first.attempt.payload)).not.toBe(
        walletCreatePayloadKey(changed.attempt.payload),
      );
    }
  });

  it("422 validation — definite rejection, попытка сбрасывается", () => {
    const attempt = {
      key: "k",
      payload: createPayload,
      phase: "executing" as const,
    };
    expect(classifyWalletWriteFailure(422, "validation_error")).toBe("definite_rejection");
    expect(applyWalletCreateAfterFailure(attempt, 422, "validation_error")).toBeNull();
  });

  it("500 и сеть — unknown, попытка сохраняется", () => {
    const attempt = {
      key: "k",
      payload: createPayload,
      phase: "executing" as const,
    };
    expect(classifyWalletWriteFailure(500, "internal")).toBe("unknown");
    expect(classifyWalletWriteFailure(0, "")).toBe("unknown");
    expect(applyWalletCreateAfterFailure(attempt, 500, "internal")?.phase).toBe("unknown");
  });

  it("409 conflict (pending) — unknown", () => {
    expect(classifyWalletWriteFailure(409, "conflict")).toBe("unknown");
    expect(classifyWalletWriteFailure(409, "duplicate_wallet_code")).toBe("definite_rejection");
  });

  it("opening timeout → Cancel → повтор confirm: тот же ключ и payload", () => {
    const sent = markOpeningSubmitExecuting({
      key: "key-1",
      payload: openingPayload,
      phase: "draft",
      openingMeta,
    });
    const unknown = applyOpeningAfterFailure(sent, 0, "");
    expect(unknown?.phase).toBe("unknown");
    const afterCancel = openingAttemptAfterCancel(unknown);
    expect(afterCancel?.key).toBe("key-1");
    const reopen = resolveOpeningConfirmAttempt(afterCancel, openingPayload, openingMeta, () => "key-2");
    expect(reopen.kind).toBe("submit");
    if (reopen.kind === "submit") {
      expect(reopen.attempt.key).toBe("key-1");
      expect(reopen.attempt.phase).toBe("draft");
    }
    const pending = pendingOpeningFromAttempt(reopen.attempt);
    expect(pending.idempotencyKey).toBe("key-1");
    expect(pending.amount).toBe("100.00");
  });

  it("opening: cancel draft до HTTP сбрасывает попытку", () => {
    const draft = resolveOpeningConfirmAttempt(null, openingPayload, openingMeta, () => "key-1");
    expect(draft.kind).toBe("submit");
    if (draft.kind !== "submit") {
      return;
    }
    expect(openingAttemptAfterCancel(draft.attempt)).toBeNull();
    expect(shouldRestoreOpeningFromAttempt(null)).toBe(false);
  });

  it("draft cancel → новые поля → confirm: modal B/2000/D2, новый ключ", () => {
    const payloadA = {
      companyId: "c1",
      walletId: "wallet-a",
      amount: "1000.00",
      effectiveAt: "2026-10-01T00:00:00+03:00",
    };
    const metaA = { walletLabel: "Счёт A", offsetUsed: "+03:00", currency: "RUB" };
    const first = resolveOpeningConfirmAttempt(null, payloadA, metaA, () => "key-a");
    expect(first.kind).toBe("submit");
    if (first.kind !== "submit") {
      return;
    }
    const afterCancel = openingAttemptAfterCancel(first.attempt);
    expect(afterCancel).toBeNull();

    const payloadB = {
      companyId: "c1",
      walletId: "wallet-b",
      amount: "2000.00",
      effectiveAt: "2026-11-15T12:00:00+03:00",
    };
    const metaB = { walletLabel: "Счёт B", offsetUsed: "+03:00", currency: "RUB" };
    const second = resolveOpeningConfirmAttempt(afterCancel, payloadB, metaB, () => "key-b");
    expect(second.kind).toBe("submit");
    if (second.kind !== "submit") {
      return;
    }
    expect(second.attempt.key).toBe("key-b");
    expect(second.attempt.phase).toBe("draft");
    const pending = pendingOpeningFromAttempt(second.attempt);
    expect(pending.walletId).toBe("wallet-b");
    expect(pending.amount).toBe("2000.00");
    expect(pending.effectiveAt).toBe("2026-11-15T12:00:00+03:00");
    expect(pending.walletLabel).toBe("Счёт B");
  });

  it("пустая дата opening — ошибка без автоподстановки", () => {
    const built = buildOpeningEffectiveAt("", "00:00", "Europe/Moscow", undefined);
    expect(built.ok).toBe(false);
    if (!built.ok) {
      expect(built.message).toContain("дату");
    }
  });

  it("timeout → смена фирмы заблокирована, attempt сохранён", () => {
    const unknown = markWalletCreateUnknown({
      key: "key-a",
      payload: createPayload,
      phase: "executing",
    });
    expect(lockedCompanyId(unknown, null)).toBe("c1");
    const guard = guardCompanySwitch("c2", lockedCompanyId(unknown, null));
    expect(guard.allowed).toBe(false);
  });

  it("смена фирмы в payload без активной попытки выдаёт новый ключ", () => {
    const otherFirm = resolveWalletCreateSubmit(
      null,
      { ...createPayload, companyId: "firm-b" },
      () => "key-b",
    );
    expect(otherFirm.kind).toBe("submit");
    if (otherFirm.kind === "submit") {
      expect(otherFirm.attempt.key).toBe("key-b");
    }
  });

  it("completeOpeningAttempt очищает состояние", () => {
    expect(completeOpeningAttempt()).toBeNull();
  });

  it("строит effective_at по поясу фирмы", () => {
    const built = buildOpeningEffectiveAt("2026-10-01", "00:00", "Europe/Moscow", undefined);
    expect(built.ok).toBe(true);
  });

  it("ключ opening payload стабилен", () => {
    expect(openingSubmitPayloadKey(openingPayload)).toBe(
      openingSubmitPayloadKey({ ...openingPayload }),
    );
    expect(formFieldsMatchOpeningAttempt(
      { key: "k", payload: openingPayload, phase: "draft" },
      openingPayload,
    )).toBe(true);
  });
});

describe("openingSummary: пользовательский вид вместо сырых значений (пункт е)", () => {
  it("сумма и дата форматируются, значение не теряется", () => {
    const text = openingSummary({ amount: "1000.00", effective_at: "2026-10-01T00:00:00+03:00" });
    expect(text).toBe("1 000,00 ₽ с 01.10.2026");
    // Сырого формата в отображении больше нет.
    expect(text).not.toContain("1000.00");
    expect(text).not.toContain("2026-10-01");
  });

  it("отсутствие остатка — словом, не нулём", () => {
    expect(openingSummary(null)).toBe("Не задан");
    expect(openingSummary(null)).not.toContain("0,00");
  });
});
