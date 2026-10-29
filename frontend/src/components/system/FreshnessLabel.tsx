import { StatusChip, type ChipTone } from "./StatusChip";

export type FreshnessValue = {
  /** Дата покрытия из API (coverage_through). */
  coverageThrough?: string | null;
  /** completeness: full / preliminary / unavailable. */
  completeness?: string | null;
  /** Нет подключённого источника. */
  missingSource?: boolean;
};

function isoToRu(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) {
    return value;
  }
  return `${match[3]}.${match[2]}.${match[1]}`;
}

export function freshnessView(state: FreshnessValue): { text: string; tone: ChipTone } {
  if (state.missingSource) {
    return { text: "Источник не подключён", tone: "warn" };
  }
  const covered = (state.coverageThrough ?? "").trim();
  if (!covered) {
    if (state.completeness === "unavailable") {
      return { text: "Данные не загружены", tone: "unavailable" };
    }
    return { text: "Дата покрытия не указана", tone: "warn" };
  }
  const date = isoToRu(covered);
  if (state.completeness === "full") {
    return { text: `Данные загружены по ${date}`, tone: "ok" };
  }
  if (state.completeness === "preliminary") {
    return { text: `Данные загружены по ${date} · период покрыт не полностью`, tone: "warn" };
  }
  return { text: `Данные загружены по ${date}`, tone: "neutral" };
}

type Props = FreshnessValue & {
  className?: string;
};

/**
 * Метка свежести: когда данные загружены и полон ли период.
 * Опирается только на поля, которые API уже отдаёт.
 */
export function FreshnessLabel({
  coverageThrough,
  completeness,
  missingSource,
  className = "",
}: Props) {
  const view = freshnessView({ coverageThrough, completeness, missingSource });
  return (
    <span className={`inline-flex items-center gap-2 ${className}`.trim()}>
      <StatusChip tone={view.tone}>{view.text}</StatusChip>
    </span>
  );
}

export { freshnessView as __freshnessView };
