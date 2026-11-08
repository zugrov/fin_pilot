import { formatDate } from "./dates";
import { formatMoney } from "./money";

export type VatThresholdBlock = {
  status: "ok" | "approaching" | "exceeded";
  ytd_revenue: string;
  threshold: string;
  percent: string;
  as_of: string;
  exceeded_month: string | null;
  obligation_from: string | null;
  partial: boolean;
  disclaimer: string;
};

export const VAT_THRESHOLD_DISCLAIMER =
  "Ориентир, не налоговая консультация: налоговая база УСН считается по поступлениям, а здесь выручка по датам признания.";

export function vatThresholdPartialNote(partial: boolean): string | null {
  return partial ? "Данные неполные: покрытие выручки за год может быть неполным." : null;
}

function formatPercentText(percent: string): string {
  const normalized = percent.replace(".00", "").replace(",", ".");
  const value = Number(normalized);
  if (!Number.isFinite(value)) {
    return percent;
  }
  return value % 1 === 0 ? String(Math.trunc(value)) : normalized.replace(".", ",");
}

function monthLabel(ym: string | null): string {
  if (!ym) {
    return "";
  }
  const padded = ym.length === 7 ? `${ym}-01` : ym;
  return formatDate(padded);
}

export function vatThresholdApproachingText(block: VatThresholdBlock): string {
  const pct = formatPercentText(block.percent);
  return (
    `Накопленная выручка с начала года: ${formatMoney(block.ytd_revenue)} из ${formatMoney(block.threshold)} ` +
    `(${pct} %). При превышении порога НДС возникает с первого числа следующего месяца.`
  );
}

export function vatThresholdExceededText(block: VatThresholdBlock): string {
  const month = monthLabel(block.exceeded_month);
  const from = block.obligation_from ? formatDate(block.obligation_from) : "";
  const pct = formatPercentText(block.percent);
  return (
    `Накопленная выручка с начала года: ${formatMoney(block.ytd_revenue)} из ${formatMoney(block.threshold)} ` +
    `(${pct} %). Порог превышен в ${month}; обязанность по НДС с ${from}. Обновите профиль: создайте версию с этой даты.`
  );
}

export function shouldShowVatThresholdBanner(
  block: VatThresholdBlock | null | undefined,
): block is VatThresholdBlock {
  return block != null && (block.status === "approaching" || block.status === "exceeded");
}
