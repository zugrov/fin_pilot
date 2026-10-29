import { BUCKETS, bucketShares } from "../../lib/receivable";
import { formatMoney } from "../../lib/money";

type Props = {
  /** Итоги по корзинам из API. */
  totals: Record<string, string>;
  /** Общий итог. null → «Нет данных». */
  total: string;
};

const HEAT_CLASS = [
  "bg-[color:var(--fp-heat-1)] text-ink border-[color:var(--fp-heat-border-1)]",
  "bg-[color:var(--fp-heat-2)] text-ink border-[color:var(--fp-heat-border-2)]",
  "bg-[color:var(--fp-heat-3)] text-surface border-[color:var(--fp-heat-border-3)]",
  "bg-[color:var(--fp-heat-4)] text-surface border-[color:var(--fp-heat-border-4)]",
];

/**
 * Тепловая карта корзин. Цвет — подсказка, смысл несут текст, процент и
 * контрастная рамка: ступени различаются рамкой, а не только заливкой.
 */
export function BucketHeatmap({ totals, total }: Props) {
  const slices = BUCKETS.map((code) => ({ code, total: totals[code] ?? null }));
  const shares = bucketShares(slices, total);

  return (
    <section className="rounded-card border border-line bg-surface p-card">
      <h2 className="mb-2 text-label text-ink-muted">Сроки долгов</h2>
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {slices.map((slice, index) => (
          <li
            key={slice.code}
            data-testid={`heat-${slice.code}`}
            data-level={index + 1}
            className={`rounded-card border-2 p-2 ${HEAT_CLASS[index]}`}
          >
            <p className="text-note">{slice.code === ">90" ? "больше 90" : slice.code} дней</p>
            <p className="mt-1 text-body font-medium fp-num">{formatMoney(slice.total)}</p>
            <p className="text-note fp-num">{shares[index]?.percent ?? "0"} %</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
