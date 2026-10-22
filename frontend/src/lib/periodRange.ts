const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function partsInTimeZone(date: Date, timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = formatter.formatToParts(date);
  const year = Number(parts.find((item) => item.type === "year")?.value ?? "1970");
  const month = Number(parts.find((item) => item.type === "month")?.value ?? "1");
  const day = Number(parts.find((item) => item.type === "day")?.value ?? "1");
  return { year, month, day };
}

function formatYmd(year: number, month: number, day: number): string {
  const mm = String(month).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  return `${year}-${mm}-${dd}`;
}

/** Первый и последний день календарного месяца в часовом поясе фирмы. */
export function monthRangeInTimeZone(timeZone: string, now = new Date()): { from: string; to: string } {
  const { year, month } = partsInTimeZone(now, timeZone);
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return {
    from: formatYmd(year, month, 1),
    to: formatYmd(year, month, lastDay),
  };
}

export function validatePeriod(from: string, to: string): { ok: true } | { ok: false; message: string } {
  if (!DATE_RE.test(from) || !DATE_RE.test(to)) {
    return { ok: false, message: "Период в формате ГГГГ-ММ-ДД." };
  }
  if (from > to) {
    return { ok: false, message: "Дата начала не может быть позже даты окончания." };
  }
  return { ok: true };
}
