import { directionLabel } from "./calendarForm";
import { parseAmountInput } from "./walletForm";

export type RuleConditionsDraft = {
  descriptionContains: string;
  counterpartyInn: string;
  direction: "" | "in" | "out";
  amountMin: string;
  amountMax: string;
};

export const EMPTY_RULE_DRAFT: {
  name: string;
  priority: string;
  categoryCode: string;
  conditions: RuleConditionsDraft;
} = {
  name: "",
  priority: "10",
  categoryCode: "",
  conditions: {
    descriptionContains: "",
    counterpartyInn: "",
    direction: "",
    amountMin: "",
    amountMax: "",
  },
};

export type RuleCreatePayload = {
  companyId: string;
  name: string;
  priority: number;
  categoryCode: string;
  conditions: Record<string, string>;
};

const INN_RE = /^\d{10}$|^\d{12}$/;

export function cashFlowSectionLabel(section: string): string {
  const map: Record<string, string> = {
    operating: "Операционная деятельность",
    investing: "Инвестиционная деятельность",
    financing: "Финансовая деятельность",
    unmapped: "Без категории",
  };
  return map[section] ?? section;
}

export function ruleEnabledLabel(enabled: boolean): string {
  return enabled ? "Включено" : "Отключено";
}

export function formatCounterparty(name: string, inn: string): string {
  const parts = [name.trim(), inn.trim()].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : "—";
}

export function buildConditionsPayload(draft: RuleConditionsDraft): Record<string, string> {
  const out: Record<string, string> = {};
  const text = draft.descriptionContains.trim();
  if (text) {
    out.description_contains = text;
  }
  const inn = draft.counterpartyInn.trim();
  if (inn) {
    out.counterparty_inn = inn;
  }
  if (draft.direction) {
    out.direction = draft.direction;
  }
  const min = draft.amountMin.trim();
  if (min) {
    out.amount_min = min;
  }
  const max = draft.amountMax.trim();
  if (max) {
    out.amount_max = max;
  }
  return out;
}

export function formatRuleConditionsHuman(conditions: Record<string, unknown>): string {
  const parts: string[] = [];
  const text = String(conditions.description_contains ?? "").trim();
  if (text) {
    parts.push(`в назначении «${text}»`);
  }
  const inn = String(conditions.counterparty_inn ?? "").trim();
  if (inn) {
    parts.push(`ИНН ${inn}`);
  }
  const dir = String(conditions.direction ?? "").trim();
  if (dir === "in" || dir === "out") {
    parts.push(directionLabel(dir));
  }
  const min = String(conditions.amount_min ?? "").trim();
  const max = String(conditions.amount_max ?? "").trim();
  if (min && max) {
    parts.push(`сумма от ${min} до ${max} ₽`);
  } else if (min) {
    parts.push(`сумма от ${min} ₽`);
  } else if (max) {
    parts.push(`сумма до ${max} ₽`);
  }
  return parts.length > 0 ? parts.join("; ") : "—";
}

export function validateRuleCreate(
  draft: typeof EMPTY_RULE_DRAFT,
): { ok: true; payload: Omit<RuleCreatePayload, "companyId"> } | { ok: false; message: string } {
  const name = draft.name.trim();
  if (!name) {
    return { ok: false, message: "Укажите название правила." };
  }
  const priorityRaw = draft.priority.trim();
  const priority = Number(priorityRaw);
  if (!Number.isInteger(priority) || priority < 1 || priority > 1000) {
    return { ok: false, message: "Приоритет — целое число от 1 до 1000." };
  }
  const categoryCode = draft.categoryCode.trim();
  if (!categoryCode) {
    return { ok: false, message: "Выберите категорию." };
  }
  const conditions = buildConditionsPayload(draft.conditions);
  if (Object.keys(conditions).length === 0) {
    return { ok: false, message: "Укажите хотя бы одно условие." };
  }
  const inn = draft.conditions.counterpartyInn.trim();
  if (inn && !INN_RE.test(inn)) {
    return { ok: false, message: "ИНН: 10 или 12 цифр." };
  }
  const min = draft.conditions.amountMin.trim();
  const max = draft.conditions.amountMax.trim();
  if (min) {
    const parsed = parseAmountInput(min);
    if (!parsed.ok) {
      return { ok: false, message: parsed.message };
    }
  }
  if (max) {
    const parsed = parseAmountInput(max);
    if (!parsed.ok) {
      return { ok: false, message: parsed.message };
    }
  }
  if (min && max) {
    const minVal = parseAmountInput(min);
    const maxVal = parseAmountInput(max);
    if (minVal.ok && maxVal.ok && Number(minVal.value) > Number(maxVal.value)) {
      return { ok: false, message: "Сумма «от» не может быть больше «до»." };
    }
  }
  return {
    ok: true,
    payload: { name, priority, categoryCode, conditions },
  };
}
