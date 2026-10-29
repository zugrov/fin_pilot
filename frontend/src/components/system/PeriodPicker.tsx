type Props = {
  from: string;
  to: string;
  onChange: (next: { from: string; to: string }) => void;
  /** Сегодняшняя дата в поясе фирмы (YYYY-MM-DD). */
  today?: string;
  /** Ошибка валидации периода. */
  error?: string;
  label?: string;
  idPrefix?: string;
};

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function shiftMonth(iso: string, delta: number): string {
  const [year, month] = iso.split("-").map(Number);
  const base = new Date(Date.UTC(year, month - 1 + delta, 1));
  return `${base.getUTCFullYear()}-${pad(base.getUTCMonth() + 1)}`;
}

function monthBounds(yearMonth: string): { from: string; to: string } {
  const [year, month] = yearMonth.split("-").map(Number);
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return { from: `${yearMonth}-01`, to: `${yearMonth}-${pad(lastDay)}` };
}

export function PeriodPicker({
  from,
  to,
  onChange,
  today,
  error,
  label = "Период",
  idPrefix = "fp-period",
}: Props) {
  const anchor = today && /^\d{4}-\d{2}-\d{2}$/.test(today) ? today : to || from;
  const currentMonth = anchor.slice(0, 7);

  const preset = (target: "current" | "previous") => {
    const yearMonth = target === "current" ? currentMonth : shiftMonth(currentMonth, -1);
    onChange(monthBounds(yearMonth));
  };

  return (
    <div className="flex flex-wrap items-end gap-2">
      <fieldset className="min-w-0">
        <legend className="mb-1 text-note text-ink-muted">{label}</legend>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-note text-ink-muted">
            с
            <input
              id={`${idPrefix}-from`}
              className="mt-1 block min-h-tap rounded-control border border-line px-2 py-1 text-body fp-num"
              type="date"
              value={from}
              onChange={(event) => onChange({ from: event.target.value, to })}
            />
          </label>
          <label className="text-note text-ink-muted">
            по
            <input
              id={`${idPrefix}-to`}
              className="mt-1 block min-h-tap rounded-control border border-line px-2 py-1 text-body fp-num"
              type="date"
              value={to}
              onChange={(event) => onChange({ from, to: event.target.value })}
            />
          </label>
          <div className="flex gap-1 pb-1">
            <button
              type="button"
              className="min-h-tap rounded-control border border-line px-2 text-note"
              onClick={() => preset("current")}
            >
              Этот месяц
            </button>
            <button
              type="button"
              className="min-h-tap rounded-control border border-line px-2 text-note"
              onClick={() => preset("previous")}
            >
              Прошлый
            </button>
          </div>
        </div>
      </fieldset>
      {error ? <p className="text-body text-danger">{error}</p> : null}
    </div>
  );
}
