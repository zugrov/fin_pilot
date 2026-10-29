/** Единый формат дат на экранах: ISO из API → «31.10.2026». */

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * «2026-10-31» → «31.10.2026». Нераспознанную строку возвращает как есть,
 * чтобы не терять данные: пусть лучше видно, что пришло.
 */
export function formatDate(value: string | null | undefined, missing = "Нет данных"): string {
  if (value === null || value === undefined || value.trim() === "") {
    return missing;
  }
  const match = ISO_DATE.exec(value.trim());
  if (!match) {
    return value;
  }
  const [, year, month, day] = match;
  return `${day}.${month}.${year}`;
}

/** Диапазон дат: «01.10.2026 — 31.10.2026». */
export function formatDateRange(from: string, to: string): string {
  return `${formatDate(from)} — ${formatDate(to)}`;
}
