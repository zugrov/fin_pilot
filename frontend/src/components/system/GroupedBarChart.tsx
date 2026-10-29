import { formatMoney, moneyToNumber } from "../../lib/money";

export type ChartSeries = { name: string; color: string };

export type GroupedBarDatum = {
  label: string;
  /** По одной денежной строке на серию; null → пустое место, не ноль. */
  values: (string | null)[];
};

type Props = {
  title: string;
  data: GroupedBarDatum[];
  series: ChartSeries[];
  unit?: string;
  id?: string;
};

/**
 * Сгруппированные столбцы без библиотек: серии рядом внутри каждой группы.
 * Смысл продублирован легендой, описанием и таблицей для скринридера.
 */
export function GroupedBarChart({ title, data, series, unit = "руб.", id = "gbar" }: Props) {
  const numbers = data.map((item) => item.values.map((value) => moneyToNumber(value)));
  const known = numbers.flat().filter((value): value is number => value !== null);
  const hasData = known.length > 0;
  const max = hasData ? Math.max(...known.map(Math.abs), 1) : 1;

  const height = 160;
  const gap = 10;
  const barWidth = 16;
  const groupWidth = series.length * barWidth + (series.length - 1) * 4;
  const width = Math.max(data.length * (groupWidth + gap), 120);
  const baseline = height - 24;

  const description = hasData
    ? data
        .map((item) => {
          const parts = item.values
            .map((value, index) => `${series[index]?.name ?? index}: ${formatMoney(value)}`)
            .join(", ");
          return `${item.label}: ${parts}`;
        })
        .join("; ")
    : "Данных для диаграммы нет";

  return (
    <figure className="rounded-card border border-line bg-surface p-card">
      <figcaption className="mb-2 text-label text-ink-muted">{title}</figcaption>

      <ul className="mb-2 flex flex-wrap gap-3" aria-hidden="true">
        {series.map((item) => (
          <li key={item.name} className="flex items-center gap-1 text-note text-ink-muted">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: item.color }} />
            {item.name}
          </li>
        ))}
      </ul>

      {hasData ? (
        <svg
          className="h-40 w-full"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-labelledby={`${id}-title`}
          aria-describedby={`${id}-desc`}
          preserveAspectRatio="none"
        >
          <title id={`${id}-title`}>{title}</title>
          <desc id={`${id}-desc`}>{description}</desc>
          <line x1={0} y1={baseline} x2={width} y2={baseline} stroke="var(--fp-line)" strokeWidth={1} />
          {data.map((item, groupIndex) => {
            const groupX = groupIndex * (groupWidth + gap) + gap / 2;
            return (
              <g key={item.label}>
                {item.values.map((_value, seriesIndex) => {
                  const number = numbers[groupIndex][seriesIndex];
                  const x = groupX + seriesIndex * (barWidth + 4);
                  if (number === null) {
                    return (
                      <rect
                        key={`${item.label}-${seriesIndex}`}
                        x={x}
                        y={baseline - 3}
                        width={barWidth}
                        height={3}
                        rx={1.5}
                        fill="var(--fp-line)"
                      />
                    );
                  }
                  const barHeight = Math.max((Math.abs(number) / max) * (baseline - 16), 2);
                  return (
                    <rect
                      key={`${item.label}-${seriesIndex}`}
                      x={x}
                      y={baseline - barHeight}
                      width={barWidth}
                      height={barHeight}
                      rx={3}
                      fill={series[seriesIndex]?.color ?? "var(--fp-info)"}
                    />
                  );
                })}
              </g>
            );
          })}
        </svg>
      ) : (
        <p className="py-6 text-body text-ink-subtle">Данных для диаграммы нет</p>
      )}

      {/* Подписи групп отдельной строкой: равномерно, как столбцы в SVG. */}
      {hasData ? (
        <ul className="mt-1 flex text-note text-ink-muted" aria-hidden="true">
          {data.map((item) => (
            <li key={item.label} className="flex-1 text-center">
              {item.label}
            </li>
          ))}
        </ul>
      ) : null}

      {/* Дублёр: те же числа таблицей, доступен всем и без SVG. */}
      <table className="mt-2 w-full text-note">
        <caption className="sr-only">
          {title}: значения по группам и сериям в {unit}
        </caption>
        <thead>
          <tr>
            <th scope="col" className="py-1 text-left font-medium text-ink-muted">
              Период
            </th>
            {series.map((item) => (
              <th key={item.name} scope="col" className="py-1 text-right font-medium text-ink-muted">
                {item.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((item) => (
            <tr key={item.label} className="border-t border-line">
              <th scope="row" className="py-1 text-left font-normal text-ink-muted">
                {item.label}
              </th>
              {item.values.map((value, seriesIndex) => (
                <td key={seriesIndex} className="py-1 text-right fp-num">
                  {formatMoney(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
