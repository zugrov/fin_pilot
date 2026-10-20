import { parseAmountInput } from "./walletForm";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export const EMPTY_PLAN_DRAFT = {
  amount: "",
  dueDate: "",
  expectedDate: "",
} as const;

export type PlanDraft = {
  amount: string;
  dueDate: string;
  expectedDate: string;
};

export type ValidationResult =
  | { ok: true; amount: string; dueDate: string; expectedDate: string }
  | { ok: false; message: string };

export function validatePlanCreate(draft: PlanDraft): ValidationResult {
  const amount = parseAmountInput(draft.amount);
  if (!amount.ok) {
    return { ok: false, message: amount.message };
  }
  const due = draft.dueDate.trim();
  if (!due) {
    return { ok: false, message: "Укажите срок оплаты." };
  }
  if (!DATE_RE.test(due)) {
    return { ok: false, message: "Срок оплаты в формате ГГГГ-ММ-ДД." };
  }
  const expected = draft.expectedDate.trim();
  if (!expected) {
    return { ok: false, message: "Укажите ожидаемую дату оплаты." };
  }
  if (!DATE_RE.test(expected)) {
    return { ok: false, message: "Ожидаемая дата в формате ГГГГ-ММ-ДД." };
  }
  return {
    ok: true,
    amount: amount.value,
    dueDate: due,
    expectedDate: expected,
  };
}

export function validateMatchAmount(raw: string): { ok: true; value: string } | { ok: false; message: string } {
  return parseAmountInput(raw);
}

export function validateExpectedDateOnly(raw: string): { ok: true; value: string } | { ok: false; message: string } {
  const expected = raw.trim();
  if (!expected) {
    return { ok: false, message: "Укажите новую ожидаемую дату оплаты." };
  }
  if (!DATE_RE.test(expected)) {
    return { ok: false, message: "Ожидаемая дата в формате ГГГГ-ММ-ДД." };
  }
  return { ok: true, value: expected };
}

export function directionLabel(direction: "in" | "out"): string {
  return direction === "in" ? "Поступление" : "Списание";
}

export function eventBelongsToCompany(eventCompanyId: string | undefined, activeCompanyId: string | null): boolean {
  if (!activeCompanyId || !eventCompanyId) {
    return false;
  }
  return eventCompanyId === activeCompanyId;
}
