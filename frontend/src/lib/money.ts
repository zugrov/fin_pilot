/** Денежные операции строками: без float, копейки через BigInt. */

export const MISSING_VALUE = "Нет данных";

type AmountParts = { negative: boolean; whole: string; fraction: string };

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
export function formatMoney(value: string | null | undefined, missing = MISSING_VALUE): string {
  if (value === null || value === undefined || value.trim() === "") {
    return missing;
  }
  const parts = parseAmount(value);
  if (!parts) {
    return missing;
  }
  const isZero = /^0+$/.test(parts.whole) && parts.fraction === "00";
  // Минус U+2212, а не ASCII-дефис: так его находит Amount и так его видят скринридеры.
  const sign = parts.negative && !isZero ? "\u2212" : "";
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

/** Число для масштабирования диаграмм; null, если строка не разбирается. */
export function moneyToNumber(value: string | null | undefined): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  const cents = toCents(value.trim());
  if (cents === null) {
    return null;
  }
  return Number(cents) / 100;
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

/** Доля в промилле на BigInt: value от total. total = 0 → 0, деления на ноль нет. */
export function permille(value: bigint, total: bigint): bigint {
  if (total === 0n) {
    return 0n;
  }
  return (value * 1000n) / total;
}

/** Промилле → подпись процента: 1250 → «12,5 %», 2000 → «20 %». */
export function percentLabel(permilleValue: bigint): string {
  const negative = permilleValue < 0n;
  const absolute = negative ? -permilleValue : permilleValue;
  const whole = absolute / 10n;
  const tenth = absolute % 10n;
  const body = tenth === 0n ? `${whole}` : `${whole},${tenth}`;
  return `${negative ? "−" : ""}${body} %`;
}

/** Денежный статус ошибки по HTTP: тип проверяется по полю status. */
export function statusOf(error: unknown): number | null {
  if (typeof error === "object" && error !== null && "status" in error) {
    const value = (error as { status: unknown }).status;
    if (typeof value === "number") {
      return value;
    }
  }
  return null;
}

export function messageOf(error: unknown): string {
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
