import { formatMoney, percentLabel, permille, toCents } from "../../lib/money";

export type DonutDatum = {
  label: string;
  /** Денежная строка доли; null → доля не рисуется и не считается нулём. */
  value: string | null;
  color: string;
};

type Props = {
  title: string;
  data: DonutDatum[];
  /** Подпись в центре кольца: обычно итог. */
  centerLabel: string;
  centerValue: string | null;
  unit?: string;
  id?: string;
};

/**
 * Кольцо долей без библиотек. Проценты считаются на BigInt (permille),
 * без float. Смысл продублирован легендой и таблицей для скринридера.
 */
export function DonutChart({ title, data, centerLabel, centerValue, unit = "руб.", id = "donut" }: Props) {
  const cents = data.map((item) => (item.value === null ? null : toCents(item.value)));
  const known = cents.filter((value): value is bigint => value !== null && value > 0n);
  const total = known.reduce((acc, value) => acc + value, 0n);
  const hasData = total > 0n;

  const size = 160;
  const stroke = 22;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;

  // Доли в промилле на BigInt: total > 0, деления на ноль нет.
  const share = (value: bigint): bigint => permille(value, total);
  const percentLabelOf = (value: bigint): string => percentLabel(share(value));

  const description = hasData
    ? data
        .map((item, index) => {
          const value = cents[index];
          if (value === null || value <= 0n) {
            return null;
          }
          return `${item.label}: ${formatMoney(item.value)} (${percentLabelOf(value)})`;
        })
        .filter((part): part is string => part !== null)
        .join("; ")
    : "Данных для диаграммы нет";

  // Сегменты рисуются по кругу от 12 часов; ненулевые доли подряд.
  let offset = 0n;

  return (
    <figure className="rounded-card border border-line bg-surface p-card">
      <figcaption className="mb-2 text-label text-ink-muted">{title}</figcaption>

      <div className="flex flex-wrap items-center gap-4">
        {hasData ? (
          <svg
            width={size}
            height={size}
            viewBox={`0 0 ${size} ${size}`}
            role="img"
            aria-labelledby={`${id}-title`}
            aria-describedby={`${id}-desc`}
            className="shrink-0"
          >
            <title id={`${id}-title`}>{title}</title>
            <desc id={`${id}-desc`}>{description}</desc>
            <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
              {cents.map((value, index) => {
                if (value === null || value <= 0n) {
                  return null;
                }
                const length = (Number(value) / Number(total)) * circumference;
                const dashOffset = -(Number(offset) / Number(total)) * circumference;
                offset += value;
                return (
                  <circle
                    key={data[index].label}
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    stroke={data[index].color}
                    strokeWidth={stroke}
                    strokeDasharray={`${length} ${circumference - length}`}
                    strokeDashoffset={dashOffset}
                  />
                );
              })}
            </g>
            <text
              x="50%"
              y="47%"
              textAnchor="middle"
              className="fill-[var(--fp-ink)]"
              fontSize="15"
              fontWeight="600"
            >
              {formatMoney(centerValue)}
            </text>
            <text
              x="50%"
              y="60%"
              textAnchor="middle"
              className="fill-[var(--fp-ink-subtle)]"
              fontSize="10"
            >
              {centerLabel}
            </text>
          </svg>
        ) : (
          <p className="py-6 text-body text-ink-subtle">Данных для диаграммы нет</p>
        )}

        <ul className="min-w-0 flex-1 space-y-1 text-note">
          {data.map((item, index) => (
            <li key={item.label} className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5 text-ink-muted">
                <span
                  aria-hidden="true"
                  className="h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: item.color }}
                />
                <span className="truncate">{item.label}</span>
              </span>
              <span className="fp-num shrink-0 text-ink">
                {cents[index] === null
                  ? formatMoney(null)
                  : `${formatMoney(item.value)} (${percentLabelOf(cents[index] as bigint)})`}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* Дублёр: те же числа таблицей, доступен всем и без SVG. */}
      <table className="mt-3 w-full text-note">
        <caption className="sr-only">
          {title}: доли в {unit}
        </caption>
        <tbody>
          {data.map((item, index) => (
            <tr key={item.label} className="border-t border-line">
              <th scope="row" className="py-1 text-left font-normal text-ink-muted">
                {item.label}
              </th>
              <td className="py-1 text-right fp-num">{formatMoney(item.value)}</td>
              <td className="py-1 text-right fp-num text-ink-muted">
                {cents[index] === null ? "—" : percentLabelOf(cents[index] as bigint)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
