import { formatMoney } from "./money";

export const NO_REVENUE = "Нет данных о выручке";

/** Выручка в подписи: количество с единицей, деньги — через форматтер. */
export function revenueDisplay(revenue: string | null, label: string): string {
  if (revenue === null) {
    return label || NO_REVENUE;
  }
  return `${label}: ${formatMoney(revenue)}`;
}