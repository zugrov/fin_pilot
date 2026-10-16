const FLAG_TEXT: Record<string, string> = {
  unclassified_operations:
    "Есть операции без категории. Они входят в поступления и выплаты.",
  intraday_approximation: "Время операции неизвестно. Остаток посчитан на конец дня.",
  missing_anchor: "Нет начального остатка. Конечный остаток неизвестен.",
  missing_opening_balance:
    "Полнота операций не подтверждена. Обороты показаны по загруженным операциям.",
  missing_revenue_source: "Источник выручки не подключён. Деньги не становятся выручкой.",
};

export function cashAmount(value: string | null, missing: string): string {
  return value ?? missing;
}

export function qualityNotes(flags: string[]): string[] {
  return flags.map((flag) => FLAG_TEXT[flag] ?? flag);
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
  return `${title} за ${dateFrom} — ${dateTo}${scope}`;
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
