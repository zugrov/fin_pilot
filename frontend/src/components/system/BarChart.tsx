import { formatMoney } from "../../lib/money";

export type BarDatum = {
  label: string;
  /** Денежная строка. Отрицательная рисуется вниз. */
  value: string | null;
  hint?: string;
};

type BarsProps = {
  title: string;
  data: BarDatum[];
  /** Единица для скринридера: «руб.». */
  unit?: string;
  id?: string;
};

function toNumber(value: string | null): number | null {
  if (value === null) {
    return null;
  }
  const cleaned = value.replace(/\s/g, "").replace(",", ".");
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Столбчатая диаграмма без библиотек. Рисуется как SVG, но смысл
 * продублирован таблицей ниже и текстовым описанием для скринридера.
 */
export function BarChart({ title, data, unit = "руб.", id = "bar" }: BarsProps) {
  const values = data.map((item) => toNumber(item.value));
  const known = values.filter((value): value is number => value !== null);
  const hasData = known.length > 0;
  const max = hasData ? Math.max(...known.map((value) => Math.abs(value)), 1) : 1;
  const height = 140;
  const gap = 8;
  const barWidth = 40;
  const width = Math.max(data.length * (barWidth + gap), 120);
  const zeroY = height / 2;

  const description = hasData
    ? data
        .map((item) => `${item.label}: ${formatMoney(item.value)}`)
        .join("; ")
    : "Данных для диаграммы нет";

  return (
    <figure className="rounded-card border border-line bg-surface p-card">
      <figcaption className="mb-2 text-label text-ink-muted">{title}</figcaption>

      {hasData ? (
        <svg
          className="h-[140px] w-full"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-labelledby={`${id}-title`}
          aria-describedby={`${id}-desc`}
          preserveAspectRatio="none"
        >
          <title id={`${id}-title`}>{title}</title>
          <desc id={`${id}-desc`}>{description}</desc>
          <line
            x1={0}
            y1={zeroY}
            x2={width}
            y2={zeroY}
            stroke="var(--fp-line)"
            strokeWidth={1}
          />
          {data.map((item, index) => {
            const value = values[index];
            const x = index * (barWidth + gap) + gap / 2;
            if (value === null) {
              return (
                <g key={item.label}>
                  <rect
                    x={x}
                    y={zeroY - 3}
                    width={barWidth}
                    height={6}
                    fill="var(--fp-line)"
                  />
                </g>
              );
            }
            const barHeight = Math.max((Math.abs(value) / max) * (height / 2 - 12), 2);
            const isNegative = value < 0;
            const y = isNegative ? zeroY : zeroY - barHeight;
            return (
              <rect
                key={item.label}
                x={x}
                y={y}
                width={barWidth}
                height={barHeight}
                rx={3}
                fill={isNegative ? "var(--fp-outflow)" : "var(--fp-inflow)"}
              />
            );
          })}
        </svg>
      ) : (
        <p className="py-6 text-body text-ink-subtle">Данных для диаграммы нет</p>
      )}

      {/* Дублёр: те же числа таблицей, доступен всем и без SVG. */}
      <table className="mt-2 w-full text-note">
        <caption className="sr-only">{title}: значения по категориям в {unit}</caption>
        <tbody>
          {data.map((item) => (
            <tr key={item.label} className="border-t border-line">
              <th scope="row" className="py-1 text-left font-normal text-ink-muted">
                {item.label}
              </th>
              <td className="py-1 text-right fp-num">{formatMoney(item.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
