import { formatDateRange } from "./dates";

const FLAG_TEXT: Record<string, string> = {
  unclassified_operations:
    "Есть операции без категории. Они входят в поступления и выплаты.",
  intraday_approximation: "Время операции неизвестно. Остаток посчитан на конец дня.",
  missing_anchor: "Нет начального остатка. Конечный остаток неизвестен.",
  missing_opening_balance:
    "Полнота операций не подтверждена. Обороты показаны по загруженным операциям.",
  missing_revenue_source: "Источник выручки не подключён. Деньги не становятся выручкой.",
  // Пункт ж: раньше технический код показывался как есть.
  partial_period:
    "Выписка загружена не за весь период. Часть операций может быть ещё не в отчёте.",
  rows_truncated: "Строк больше, чем помещается в отчёт. Сузьте период или дату среза.",
};

/** Флаг без записи в словаре: показываем по-русски, без машинного кода. */
const UNKNOWN_FLAG_TEXT = "У отчёта есть замечание к полноте данных.";

export function flagText(flag: string): string {
  return FLAG_TEXT[flag] ?? UNKNOWN_FLAG_TEXT;
}

export function cashAmount(value: string | null, missing: string): string {
  return value ?? missing;
}

export function qualityNotes(flags: string[]): string[] {
  return flags.map(flagText);
}

export function isLoadedOnly(flags: string[]): boolean {
  return flags.includes("missing_opening_balance") || flags.includes("missing_anchor");
}

export function flowLabel(
  title: string,
  dateFrom: string,
  dateTo: string,
  loadedOnly: boolean,
): string {
  const scope = loadedOnly ? ", по загруженным операциям" : "";
  return `${title} за ${formatDateRange(dateFrom, dateTo)}${scope}`;
}

export function balanceMoment(asOf: string): string {
  const moment = new Date(asOf);
  if (Number.isNaN(moment.getTime())) {
    return asOf;
  }
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(moment);
}

export function balanceLabel(asOf: string): string {
  return `Остаток на ${balanceMoment(asOf)}`;
}
