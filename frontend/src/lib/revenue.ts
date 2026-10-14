export const NO_REVENUE = "Нет данных о выручке";

export function revenueDisplay(revenue: string | null, label: string): string {
  if (revenue === null) {
    return label || NO_REVENUE;
  }
  return `${label}: ${revenue}`;
}
