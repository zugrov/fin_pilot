export const SECTIONS = ["operating", "investing", "financing", "technical", "unmapped"] as const;

export type SectionCode = (typeof SECTIONS)[number];

export const MISSING_VALUE = "Нет данных";

const SECTION_LABEL: Record<SectionCode, string> = {
  operating: "Операционная деятельность",
  investing: "Инвестиционная деятельность",
  financing: "Финансовая деятельность",
  technical: "Технические операции",
  unmapped: "Не разнесено по видам деятельности",
};

const SECTION_HINT: Partial<Record<SectionCode, string>> = {
  technical:
    "Переводы между своими счетами и служебные движения. Это не деловые обороты.",
  unmapped:
    "Операции без категории: пока непонятно, к какому виду деятельности они относятся.",
};

const COMPLETENESS_LABEL: Record<string, string> = {
  unavailable: "Нет данных",
  preliminary: "Предварительно",
  full: "Полно",
};

const COMPLETENESS_NOTE: Record<string, string> = {
  unavailable:
    "За этот период не загружено ни одной операции. Пустая таблица означает отсутствие данных, а не нулевые обороты.",
  preliminary:
    "Данные неполные: часть операций без категории или загружены не все дни. Итоги могут измениться.",
  full: "Все операции за период загружены, период покрыт выписками.",
};

const FLAG_TEXT: Record<string, string> = {
  unclassified_operations:
    "Есть операции без категории — они попали в «Не разнесено по видам деятельности».",
  missing_opening_balance:
    "Нет начального остатка по счёту — остаток на конец периода не считается.",
  missing_anchor: "Нет начального остатка по счёту — остаток на конец периода не считается.",
  partial_period: "Выписки закрывают не весь период — часть дней отсутствует.",
  manual_entry_only: "Операции заведены вручную, без выписки: полноту подтвердить нельзя.",
  coverage_unverified: "Полнота покрытия периода не подтверждена сверкой с банком.",
};

export const DRILLDOWN_LIMIT = 100;

export function sectionLabel(code: string): string {
  return SECTION_LABEL[code as SectionCode] ?? code;
}

export function sectionHint(code: string): string | null {
  return SECTION_HINT[code as SectionCode] ?? null;
}

export function completenessLabel(value: string | null | undefined): string {
  if (!value) {
    return MISSING_VALUE;
  }
  return COMPLETENESS_LABEL[value] ?? MISSING_VALUE;
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

export function hasUnclassified(flags: readonly string[]): boolean {
  return flags.includes("unclassified_operations");
}

type AmountParts = { negative: boolean; whole: string; fraction: string };

/** Разбор денежной строки без float: только цифры и точка. */
function parseAmount(raw: string): AmountParts | null {
  const trimmed = raw.trim();
  if (!/^-?\d+(?:\.\d+)?$/.test(trimmed)) {
    return null;
  }
  const negative = trimmed.startsWith("-");
  const body = negative ? trimmed.slice(1) : trimmed;
  const [whole, fraction = ""] = body.split(".");
  return { negative, whole, fraction: `${fraction}00`.slice(0, 2) };
}

function groupThousands(whole: string): string {
  const padded = whole.replace(/^0+(?=\d)/, "");
  return padded.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/** «27000.00» → «27 000,00 ₽»; null → «Нет данных», а не нуль. */
export function formatMoney(
  value: string | null | undefined,
  missing: string = MISSING_VALUE,
): string {
  if (value === null || value === undefined || value.trim() === "") {
    return missing;
  }
  const parts = parseAmount(value);
  if (!parts) {
    return missing;
  }
  const isZero = /^0+$/.test(parts.whole) && parts.fraction === "00";
  const sign = parts.negative && !isZero ? "-" : "";
  return `${sign}${groupThousands(parts.whole)},${parts.fraction} ₽`;
}

export function toCents(value: string): bigint | null {
  const parts = parseAmount(value);
  if (!parts) {
    return null;
  }
  const sign = parts.negative ? -1n : 1n;
  return sign * (BigInt(parts.whole) * 100n + BigInt(parts.fraction));
}

export function fromCents(cents: bigint): string {
  const negative = cents < 0n;
  const absolute = negative ? -cents : cents;
  const whole = absolute / 100n;
  const fraction = absolute % 100n;
  return `${negative ? "-" : ""}${whole}.${fraction.toString().padStart(2, "0")}`;
}

/** Сумма денежных строк; null, если хотя бы одна строка не разбирается. */
export function sumMoney(values: readonly (string | null | undefined)[]): string | null {
  let total = 0n;
  for (const value of values) {
    if (value === null || value === undefined || value.trim() === "") {
      return null;
    }
    const cents = toCents(value);
    if (cents === null) {
      return null;
    }
    total += cents;
  }
  return fromCents(total);
}

export function netOf(sectionIn: string, sectionOut: string): string | null {
  return sumMoney([sectionIn, `-${sectionOut}`]);
}

export function sectionNetText(sectionIn: string, sectionOut: string): string {
  const net = netOf(sectionIn, sectionOut);
  return net === null ? MISSING_VALUE : formatMoney(net);
}

export function isDrilldownTruncated(ids: readonly string[] | undefined): boolean {
  return (ids?.length ?? 0) >= DRILLDOWN_LIMIT;
}

export function drilldownNotice(): string {
  return "Показаны первые 100 операций этой группы. Чтобы увидеть остальные, сузьте период.";
}

export function emptyStateText(): string {
  return "За выбранный период операций нет. Загрузите выписку в разделе «Импорт».";
}

export function periodCaption(from: string, to: string): string {
  return `Период: ${from} — ${to}`;
}

function statusOf(error: unknown): number | null {
  if (typeof error === "object" && error !== null && "status" in error) {
    const value = (error as { status: unknown }).status;
    if (typeof value === "number") {
      return value;
    }
  }
  return null;
}

function messageOf(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  if (typeof error === "object" && error !== null && "message" in error) {
    const value = (error as { message: unknown }).message;
    if (typeof value === "string" && value) {
      return value;
    }
  }
  return "";
}
export function cashflowErrorText(error: unknown): string {
  const status = statusOf(error);
  if (status === 403) {
    return "Нет доступа к этой фирме. Выберите другую фирму или попросите владельца дать доступ.";
  }
  if (status === 404) {
    return "Фирма не найдена или у вас нет к ней доступа.";
  }
  if (status === 422) {
    return "Проверьте даты периода: формат ГГГГ-ММ-ДД, начало не позже конца.";
  }
  if (status === 402) {
    return "Оплаченный период закончился. Продлите тариф, чтобы смотреть отчёт.";
  }
  const message = messageOf(error);
  if (status !== null && message) {
    return message;
  }
  return "Не удалось загрузить отчёт. Проверьте соединение и попробуйте ещё раз.";
}

export function totalsMismatch(netExternal: string, sectionNets: readonly (string | null)[]): boolean {
  if (sectionNets.some((item) => item === null)) {
    return false;
  }
  const expected = toCents(netExternal);
  const actual = sumMoney(sectionNets as string[]);
  if (expected === null || actual === null) {
    return false;
  }
  return expected !== toCents(actual);
}
