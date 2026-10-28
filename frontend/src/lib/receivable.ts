export const BUCKETS = ["0-30", "31-60", "61-90", ">90"] as const;

export type BucketCode = (typeof BUCKETS)[number];

export const ROWS_LIMIT = 500;

export {
  formatMoney,
  MISSING_VALUE,
  sumMoney,
  toCents,
} from "./money";

import { messageOf, statusOf, toCents } from "./money";

const BUCKET_LABEL: Record<BucketCode, string> = {
  "0-30": "до 30 дней",
  "31-60": "31–60 дней",
  "61-90": "61–90 дней",
  ">90": "больше 90 дней",
};

const BUCKET_HINT: Record<BucketCode, string> = {
  "0-30": "Свежие долги, обычный срок оплаты.",
  "31-60": "Просрочка больше месяца.",
  "61-90": "Просрочка больше двух месяцев.",
  ">90": "Долг висит больше трёх месяцев — риск не получить деньги.",
};

const COMPLETENESS_LABEL: Record<string, string> = {
  unavailable: "Нет данных о продажах",
  preliminary: "Предварительно",
  full: "Полно",
};

const COMPLETENESS_NOTE: Record<string, string> = {
  unavailable:
    "Продажи за период не загружены, поэтому задолженность посчитать нельзя. Это отсутствие данных, а не нулевой долг.",
  preliminary:
    "Данные неполные: загружены не все продажи или период покрыт не полностью. Итог может измениться.",
  full: "Все продажи за период загружены, период покрыт выписками.",
};

const FLAG_TEXT: Record<string, string> = {
  missing_revenue_source:
    "Источник продаж не подключён — задолженность покупателей посчитать нельзя. Подключите источник в «Импорте».",
  partial_period: "Данные покрывают не весь период.",
  missing_counterparty: "У части строк не указан контрагент.",
  coverage_unverified: "Полнота периода не подтверждена сверкой.",
};

export function bucketLabel(code: string): string {
  return BUCKET_LABEL[code as BucketCode] ?? code;
}

export function bucketHint(code: string): string | null {
  return BUCKET_HINT[code as BucketCode] ?? null;
}

export function completenessLabel(value: string | null | undefined): string {
  if (!value) {
    return "Нет данных";
  }
  return COMPLETENESS_LABEL[value] ?? "Нет данных";
}

export function completenessNote(value: string | null | undefined): string {
  if (!value) {
    return COMPLETENESS_NOTE.unavailable;
  }
  return COMPLETENESS_NOTE[value] ?? "Состояние данных не определено.";
}

export function isUnavailable(value: string | null | undefined): boolean {
  return value === "unavailable";
}

export function flagNotes(flags: readonly string[]): string[] {
  return flags.map((flag) => FLAG_TEXT[flag] ?? flag);
}

export function hasMissingRevenueSource(flags: readonly string[]): boolean {
  return flags.includes("missing_revenue_source");
}

export type BucketSlice = { code: string; total: string | null };

function permille(value: bigint, total: bigint): bigint {
  if (total === 0n) {
    return 0n;
  }
  return (value * 1000n) / total;
}

function formatPermille(value: bigint): string {
  const negative = value < 0n;
  const absolute = negative ? -value : value;
  const whole = absolute / 10n;
  const tenth = absolute % 10n;
  const text = tenth === 0n ? whole.toString() : `${whole},${tenth}`;
  return negative ? `-${text}` : text;
}

/** Доли корзин в процентах. При нулевом итоге — 0 %, без деления на ноль. */
export function bucketShares(
  slices: readonly BucketSlice[],
  total: string | null,
): { code: string; percent: string }[] {
  const totalCents = total === null ? null : toCents(total);
  if (totalCents === null || totalCents === 0n) {
    return slices.map((item) => ({ code: item.code, percent: "0" }));
  }
  return slices.map((item) => {
    const cents = item.total === null ? 0n : (toCents(item.total) ?? 0n);
    return { code: item.code, percent: formatPermille(permille(cents, totalCents)) };
  });
}

export function bucketPercentText(percent: string): string {
  return `${percent} %`;
}

export function counterpartyLabel(
  counterparty: { name?: string | null; inn?: string | null } | null | undefined,
): string {
  const name = (counterparty?.name ?? "").trim();
  const inn = (counterparty?.inn ?? "").trim();
  if (!name && !inn) {
    return "Контрагент не указан";
  }
  if (name && inn) {
    return `${name} (ИНН ${inn})`;
  }
  return name || `ИНН ${inn}`;
}

export function documentLabel(
  document: { number?: string | null; external_id?: string | null } | null | undefined,
): string {
  const number = (document?.number ?? "").trim();
  const external = (document?.external_id ?? "").trim();
  if (number && external) {
    return `${number} · ${external}`;
  }
  return number || external || "—";
}

export function ageDaysLabel(ageDays: number | null | undefined): string {
  if (ageDays === null || ageDays === undefined || Number.isNaN(ageDays)) {
    return "Нет данных";
  }
  return String(ageDays);
}

export function isRowsTruncated(rows: readonly unknown[], rowsTruncated: boolean): boolean {
  return rowsTruncated || rows.length >= ROWS_LIMIT;
}

export function truncatedNotice(limit: number = ROWS_LIMIT): string {
  return `Показаны не все строки (лимит ${limit}). Сузьте дату среза.`;
}

export function emptyStateText(): string {
  return "На выбранную дату долгов нет. Если продажи загружены не полностью, проверьте «Импорт».";
}

export function unallocatedTitle(): string {
  return "Поступления без привязки к продаже";
}

export function unallocatedNote(): string {
  return "Деньги пришли, но не связаны с конкретной продажей: долг по ним не уменьшен.";
}

export function orphanTitle(): string {
  return "Возвраты без связанной продажи";
}

export function orphanNote(): string {
  return "Возврат проведён, но продажа не найдена или отменена. Сумма показана со знаком минус.";
}

export function debtBasisNote(): string {
  return "Это задолженность покупателей перед вами, а не деньги на счёте.";
}

/** Сегодняшняя дата в часовом поясе фирмы, а не в поясе браузера. */
export function todayInTimeZone(timeZone: string, now: Date = new Date()): string {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: timeZone || "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = formatter.formatToParts(now);
  const year = parts.find((item) => item.type === "year")?.value ?? "1970";
  const month = parts.find((item) => item.type === "month")?.value ?? "01";
  const day = parts.find((item) => item.type === "day")?.value ?? "01";
  return `${year}-${month}-${day}`;
}

export function asOfCaption(asOf: string): string {
  return `Долги на ${asOf}`;
}

export function receivableErrorText(error: unknown): string {
  const status = statusOf(error);
  if (status === 403) {
    return "Нет доступа к этой фирме. Выберите другую фирму или попросите владельца дать доступ.";
  }
  if (status === 404) {
    return "Фирма не найдена или у вас нет к ней доступа.";
  }
  if (status === 422) {
    return "Проверьте дату среза: формат ГГГГ-ММ-ДД.";
  }
  if (status === 402) {
    return "Оплаченный период закончился. Продлите тариф, чтобы смотреть отчёт.";
  }
  const message = messageOf(error);
  if (status !== null && message) {
    return message;
  }
  return "Не удалось загрузить задолженность. Проверьте соединение и попробуйте ещё раз.";
}
