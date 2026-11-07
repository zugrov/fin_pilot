import { companyDate } from "./forecast";

/** Первое число следующего месяца по часовому поясу компании (YYYY-MM-01). */
export function defaultEffectiveFromMonth(timeZone: string, now = new Date()): string {
  const today = companyDate(timeZone, now);
  const [yearText, monthText] = today.split("-");
  let year = Number(yearText);
  let month = Number(monthText) + 1;
  if (month > 12) {
    month = 1;
    year += 1;
  }
  const monthPadded = String(month).padStart(2, "0");
  return `${year}-${monthPadded}-01`;
}
