import { formatDate } from "../../src/lib/dates";
import { companyDate } from "../../src/lib/forecast";

const E2E_COMPANY_TZ = "Europe/Moscow";

/** YYYY-MM для input[type=month]: текущий календарный месяц компании + N месяцев. */
export function companyYearMonthPlus(timeZone: string, monthsAhead: number, now = new Date()): string {
  const local = companyDate(timeZone, now);
  let year = Number(local.slice(0, 4));
  let month = Number(local.slice(5, 7)) + monthsAhead;
  while (month > 12) {
    month -= 12;
    year += 1;
  }
  while (month < 1) {
    month += 12;
    year -= 1;
  }
  return `${year}-${String(month).padStart(2, "0")}`;
}

export function e2eFutureVersionMonthInput(monthsAhead = 2, now = new Date()): string {
  return companyYearMonthPlus(E2E_COMPANY_TZ, monthsAhead, now);
}

export function effectiveFromFirstDay(yearMonth: string): string {
  return `${yearMonth}-01`;
}

/** Как на карточке: formatDate(effective_from). */
export function formatEffectiveFromLabel(yearMonth: string): string {
  return formatDate(effectiveFromFirstDay(yearMonth));
}
