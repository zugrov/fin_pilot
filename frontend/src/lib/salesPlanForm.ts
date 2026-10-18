import {
  applyWalletCreateAfterFailure,
  classifyWalletWriteFailure,
  guardCompanySwitch,
  isAttemptAwaitingOutcome,
  type IdempotentAttempt,
} from "./walletForm";

export type RevenueCreatePayload = {
  companyId: string;
  recognitionDate: string;
  amountInc: string;
  amountEx: string;
  vat: string;
  documentNumber: string;
  externalId: string;
};

export type PlanCreatePayload = {
  companyId: string;
  direction: "in" | "out";
  amount: string;
  dueDate: string;
  expectedDate: string;
};

export type RevenueMatchPayload = {
  companyId: string;
  revenueEntryId: string;
  cashTransactionId: string;
  amount: string;
};

export type PlanMatchPayload = {
  companyId: string;
  eventId: string;
  cashTransactionId: string;
  amount: string;
};

export type SubmitResolution<T> =
  | { kind: "submit"; attempt: IdempotentAttempt<T> }
  | { kind: "blocked"; attempt: IdempotentAttempt<T> };

export function payloadKey(payload: unknown): string {
  return JSON.stringify(payload);
}

export function resolveSubmit<T>(
  prior: IdempotentAttempt<T> | null,
  next: T,
  freshKey: () => string,
): SubmitResolution<T> {
  if (prior && isAttemptAwaitingOutcome(prior)) {
    if (payloadKey(prior.payload) !== payloadKey(next)) {
      return { kind: "blocked", attempt: prior };
    }
    return {
      kind: "submit",
      attempt: { ...prior, phase: "executing" },
    };
  }
  return {
    kind: "submit",
    attempt: { key: freshKey(), payload: next, phase: "executing" },
  };
}

export function applyAfterFailure<T>(
  attempt: IdempotentAttempt<T>,
  status: number,
  code: string,
): IdempotentAttempt<T> | null {
  if (classifyWalletWriteFailure(status, code) === "definite_rejection") {
    return null;
  }
  return { ...attempt, phase: "unknown" };
}

export function shouldBlockFieldEdit<T>(attempt: IdempotentAttempt<T> | null): boolean {
  return isAttemptAwaitingOutcome(attempt);
}

export function lockedCompanyFromAttempts(
  attempts: Array<IdempotentAttempt<{ companyId: string }> | null>,
): string | null {
  for (const attempt of attempts) {
    if (attempt && isAttemptAwaitingOutcome(attempt)) {
      return attempt.payload.companyId;
    }
  }
  return null;
}

export {
  applyWalletCreateAfterFailure,
  guardCompanySwitch,
  isAttemptAwaitingOutcome,
  type IdempotentAttempt,
};

export function writeFailureMessage(
  message: string,
  status: number,
  code: string,
): string {
  const next = applyAfterFailure(
    { key: "", payload: { companyId: "" }, phase: "executing" },
    status,
    code,
  );
  if (next === null) {
    return message;
  }
  return `${message} Ответ сервера не получен. Параметры зафиксированы — повторите отправку с тем же ключом.`;
}
