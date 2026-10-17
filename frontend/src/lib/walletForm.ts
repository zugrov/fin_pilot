const AMOUNT_RE = /^\d+\.\d{2}$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TIME_RE = /^\d{2}:\d{2}$/;
const OFFSET_RE = /^[+-]\d{2}:\d{2}$/;

export type AmountParseResult =
  | { ok: true; value: string }
  | { ok: false; message: string };

export type WalletCreatePayload = {
  companyId: string;
  name: string;
  type: string;
  code: string;
};

export type OpeningSubmitPayload = {
  companyId: string;
  walletId: string;
  amount: string;
  effectiveAt: string;
};

/** draft — opening до HTTP; executing — запрос в сети; unknown — отправлено, исход не подтверждён */
export type AttemptPhase = "draft" | "executing" | "unknown";

export type OpeningAttemptMeta = {
  walletLabel: string;
  offsetUsed: string;
  currency: string;
};

export type IdempotentAttempt<T> = {
  key: string;
  payload: T;
  phase: AttemptPhase;
  openingMeta?: OpeningAttemptMeta;
};

export type SubmitResolution<T> =
  | { kind: "submit"; attempt: IdempotentAttempt<T> }
  | { kind: "blocked"; attempt: IdempotentAttempt<T> };

export const UNKNOWN_OUTCOME_MESSAGE =
  "Ответ сервера не получен. Параметры зафиксированы — повторите отправку с тем же ключом.";

export const COMPANY_SWITCH_BLOCKED_MESSAGE =
  "Смена фирмы недоступна, пока не подтверждён результат предыдущего действия.";

export const FIELD_EDIT_BLOCKED_MESSAGE =
  "Нельзя менять параметры, пока не подтверждён результат отправки. Повторите или дождитесь ответа.";

export function parseAmountInput(raw: string): AmountParseResult {
  const trimmed = raw.trim();
  if (!AMOUNT_RE.test(trimmed)) {
    return { ok: false, message: "Сумма в формате 1234.56" };
  }
  return { ok: true, value: trimmed };
}

export function balanceLabel(balance: string | null, qualityFlags: string[]): string {
  if (balance !== null) {
    return balance;
  }
  if (qualityFlags.includes("missing_anchor")) {
    return "Нет начального остатка";
  }
  return "Нет данных";
}

export function openingSummary(
  opening: { amount: string; effective_at: string } | null | undefined,
): string {
  if (!opening) {
    return "Не задан";
  }
  return `${opening.amount} с ${opening.effective_at}`;
}

export function offsetForTimeZone(
  timeZone: string,
  date: string,
  time: string,
): string | null {
  if (!DATE_RE.test(date) || !TIME_RE.test(time)) {
    return null;
  }
  try {
    const [year, month, day] = date.split("-").map(Number);
    const [hour, minute] = time.split(":").map(Number);
    const utcGuess = Date.UTC(year, month - 1, day, hour, minute, 0);
    const formatter = new Intl.DateTimeFormat("en-US", {
      timeZone,
      timeZoneName: "longOffset",
    });
    const parts = formatter.formatToParts(new Date(utcGuess));
    const zone = parts.find((part) => part.type === "timeZoneName")?.value ?? "";
    const match = zone.match(/GMT([+-])(\d{1,2})(?::(\d{2}))?/);
    if (!match) {
      return null;
    }
    const sign = match[1];
    const hours = match[2].padStart(2, "0");
    const minutes = (match[3] ?? "00").padStart(2, "0");
    return `${sign}${hours}:${minutes}`;
  } catch {
    return null;
  }
}

export type EffectiveAtResult =
  | { ok: true; iso: string; offsetUsed: string }
  | { ok: false; message: string };

export function buildOpeningEffectiveAt(
  date: string,
  time: string,
  companyTimeZone: string | undefined,
  manualOffset: string | undefined,
): EffectiveAtResult {
  if (!date.trim()) {
    return { ok: false, message: "Выберите дату начального остатка" };
  }
  if (!DATE_RE.test(date)) {
    return { ok: false, message: "Дата в формате ГГГГ-ММ-ДД" };
  }
  const normalizedTime = TIME_RE.test(time) ? time : "00:00";
  let offset = manualOffset?.trim();
  if (offset && !OFFSET_RE.test(offset)) {
    return { ok: false, message: "Смещение в формате +03:00" };
  }
  if (!offset) {
    if (!companyTimeZone) {
      return {
        ok: false,
        message: "Укажите смещение UTC или выберите фирму с часовым поясом",
      };
    }
    const derived = offsetForTimeZone(companyTimeZone, date, normalizedTime);
    if (!derived) {
      return {
        ok: false,
        message: "Не удалось определить смещение по поясу фирмы — укажите вручную",
      };
    }
    offset = derived;
  }
  return {
    ok: true,
    iso: `${date}T${normalizedTime}:00${offset}`,
    offsetUsed: offset,
  };
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export function walletCreatePayloadKey(payload: WalletCreatePayload): string {
  return JSON.stringify(payload);
}

export function openingSubmitPayloadKey(payload: OpeningSubmitPayload): string {
  return JSON.stringify(payload);
}

export function isAttemptAwaitingOutcome<T>(attempt: IdempotentAttempt<T> | null): boolean {
  return attempt?.phase === "unknown" || attempt?.phase === "executing";
}

export function lockedCompanyId(
  create: IdempotentAttempt<WalletCreatePayload> | null,
  opening: IdempotentAttempt<OpeningSubmitPayload> | null,
): string | null {
  if (create && isAttemptAwaitingOutcome(create)) {
    return create.payload.companyId;
  }
  if (opening && isAttemptAwaitingOutcome(opening)) {
    return opening.payload.companyId;
  }
  return null;
}

export function guardCompanySwitch(
  nextCompanyId: string,
  lockedId: string | null,
): { allowed: true } | { allowed: false; message: string } {
  if (lockedId && nextCompanyId !== lockedId) {
    return { allowed: false, message: COMPANY_SWITCH_BLOCKED_MESSAGE };
  }
  return { allowed: true };
}

export function shouldBlockWalletCreateFieldEdit(
  attempt: IdempotentAttempt<WalletCreatePayload> | null,
): boolean {
  return isAttemptAwaitingOutcome(attempt);
}

export function shouldBlockOpeningFieldEdit(
  attempt: IdempotentAttempt<OpeningSubmitPayload> | null,
): boolean {
  return isAttemptAwaitingOutcome(attempt);
}

/** Коды/статусы API, при которых запись на сервере не создаётся — можно начать новое действие. */
export function classifyWalletWriteFailure(
  status: number,
  code: string,
): "unknown" | "definite_rejection" {
  if (status === 0 || status >= 500) {
    return "unknown";
  }
  if (status === 402 || status === 403 || status === 404 || status === 422 || status === 400) {
    return "definite_rejection";
  }
  if (status === 409) {
    if (code === "conflict") {
      return "unknown";
    }
    return "definite_rejection";
  }
  return "unknown";
}

export function applyWalletCreateAfterFailure(
  attempt: IdempotentAttempt<WalletCreatePayload>,
  status: number,
  code: string,
): IdempotentAttempt<WalletCreatePayload> | null {
  if (classifyWalletWriteFailure(status, code) === "definite_rejection") {
    return null;
  }
  return { ...attempt, phase: "unknown" };
}

export function applyOpeningAfterFailure(
  attempt: IdempotentAttempt<OpeningSubmitPayload>,
  status: number,
  code: string,
): IdempotentAttempt<OpeningSubmitPayload> | null {
  if (classifyWalletWriteFailure(status, code) === "definite_rejection") {
    return null;
  }
  return { ...attempt, phase: "unknown" };
}

export function markWalletCreateExecuting(
  attempt: IdempotentAttempt<WalletCreatePayload>,
): IdempotentAttempt<WalletCreatePayload> {
  return { ...attempt, phase: "executing" };
}

export function markWalletCreateUnknown(
  attempt: IdempotentAttempt<WalletCreatePayload>,
): IdempotentAttempt<WalletCreatePayload> {
  return { ...attempt, phase: "unknown" };
}

export function resolveWalletCreateSubmit(
  prior: IdempotentAttempt<WalletCreatePayload> | null,
  next: WalletCreatePayload,
  freshKey: () => string,
): SubmitResolution<WalletCreatePayload> {
  if (prior && isAttemptAwaitingOutcome(prior)) {
    if (walletCreatePayloadKey(prior.payload) !== walletCreatePayloadKey(next)) {
      return { kind: "blocked", attempt: prior };
    }
    return {
      kind: "submit",
      attempt: markWalletCreateExecuting(prior),
    };
  }
  return {
    kind: "submit",
    attempt: {
      key: freshKey(),
      payload: next,
      phase: "executing",
    },
  };
}

export function completeWalletCreateAttempt(): null {
  return null;
}

export function resolveOpeningConfirmAttempt(
  prior: IdempotentAttempt<OpeningSubmitPayload> | null,
  next: OpeningSubmitPayload,
  meta: OpeningAttemptMeta,
  freshKey: () => string,
): SubmitResolution<OpeningSubmitPayload> {
  if (prior && isAttemptAwaitingOutcome(prior)) {
    if (openingSubmitPayloadKey(prior.payload) !== openingSubmitPayloadKey(next)) {
      return { kind: "blocked", attempt: prior };
    }
    return {
      kind: "submit",
      attempt: {
        ...prior,
        phase: prior.phase === "unknown" ? "draft" : prior.phase,
        openingMeta: meta,
      },
    };
  }
  if (
    prior &&
    prior.phase === "draft" &&
    openingSubmitPayloadKey(prior.payload) === openingSubmitPayloadKey(next)
  ) {
    return {
      kind: "submit",
      attempt: { ...prior, openingMeta: meta },
    };
  }
  return {
    kind: "submit",
    attempt: {
      key: freshKey(),
      payload: next,
      phase: "draft",
      openingMeta: meta,
    },
  };
}

export function markOpeningSubmitExecuting(
  attempt: IdempotentAttempt<OpeningSubmitPayload>,
): IdempotentAttempt<OpeningSubmitPayload> {
  return { ...attempt, phase: "executing" };
}

/** Draft до HTTP: отмена сбрасывает попытку. Unknown/executing — сохраняем для повтора. */
export function openingAttemptAfterCancel(
  prior: IdempotentAttempt<OpeningSubmitPayload> | null,
): IdempotentAttempt<OpeningSubmitPayload> | null {
  if (!prior) {
    return null;
  }
  if (prior.phase === "draft") {
    return null;
  }
  return prior;
}

export function shouldRestoreOpeningFromAttempt(
  attempt: IdempotentAttempt<OpeningSubmitPayload> | null,
): boolean {
  return attempt?.phase === "unknown";
}

export function completeOpeningAttempt(): null {
  return null;
}

export function formFieldsMatchOpeningAttempt(
  attempt: IdempotentAttempt<OpeningSubmitPayload>,
  next: OpeningSubmitPayload,
): boolean {
  return openingSubmitPayloadKey(attempt.payload) === openingSubmitPayloadKey(next);
}

export function pendingOpeningFromAttempt(
  attempt: IdempotentAttempt<OpeningSubmitPayload>,
): OpeningSubmitPayload & OpeningAttemptMeta & { idempotencyKey: string } {
  const meta = attempt.openingMeta ?? {
    walletLabel: attempt.payload.walletId,
    offsetUsed: "",
    currency: "RUB",
  };
  return {
    ...attempt.payload,
    ...meta,
    idempotencyKey: attempt.key,
  };
}
