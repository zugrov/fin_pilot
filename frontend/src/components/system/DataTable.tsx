import { useState, type ReactNode } from "react";

export type Density = "compact" | "roomy";

type Column<T> = {
  key: string;
  header: string;
  /** Числовая колонка: выравнивание вправо и табличные цифры. */
  numeric?: boolean;
  render: (row: T) => ReactNode;
};

type Props<T> = {
  /** Подпись таблицы для скринридера и видимый заголовок. */
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Строка итога: показывается в <tfoot>. */
  footer?: ReactNode;
  /** Переключатель плотности; по умолчанию компактно. */
  showDensityToggle?: boolean;
  /** Карточки для узких экранов: тот же набор данных. */
  mobileCard?: (row: T) => ReactNode;
  /** Сообщение, если строк нет. */
  emptyText?: string;
};

export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  footer,
  showDensityToggle = true,
  mobileCard,
  emptyText = "Нет строк за выбранный период.",
}: Props<T>) {
  const [density, setDensity] = useState<Density>("compact");
  const cellY = density === "compact" ? "py-1" : "py-3";

  return (
    <section className="rounded-card border border-line bg-surface">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h2 className="text-label text-ink-muted">{caption}</h2>
        {showDensityToggle ? (
          <div className="flex items-center gap-1 text-note">
            <span className="text-ink-subtle" id="fp-density-label">
              Плотность
            </span>
            <div
              role="group"
              aria-labelledby="fp-density-label"
              className="inline-flex overflow-hidden rounded-control border border-line"
            >
              <button
                type="button"
                aria-pressed={density === "compact"}
                className={`min-h-tap min-w-tap px-2 ${
                  density === "compact" ? "bg-ink text-surface" : "bg-surface text-ink"
                }`}
                onClick={() => setDensity("compact")}
              >
                Компактно
              </button>
              <button
                type="button"
                aria-pressed={density === "roomy"}
                className={`min-h-tap min-w-tap px-2 ${
                  density === "roomy" ? "bg-ink text-surface" : "bg-surface text-ink"
                }`}
                onClick={() => setDensity("roomy")}
              >
                Просторно
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <p className="px-3 py-4 text-body text-ink-muted">{emptyText}</p>
      ) : (
        <>
          {mobileCard ? (
            <ul className="sm:hidden" data-testid="data-table-cards">
              {rows.map((row) => (
                <li key={rowKey(row)} className="border-b border-line px-3 py-2 last:border-b-0">
                  {mobileCard(row)}
                </li>
              ))}
            </ul>
          ) : null}

          <table
            className={`w-full text-body ${mobileCard ? "hidden sm:table" : "table"}`}
            data-testid="data-table"
            data-density={density}
          >
            <caption className="sr-only">{caption}</caption>
            <thead>
              <tr className="border-b border-line bg-canvas">
                {columns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    className={`px-3 ${cellY} font-medium text-ink-muted ${
                      column.numeric ? "text-right" : "text-left"
                    }`}
                  >
                    {column.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={rowKey(row)} className="border-b border-line last:border-b-0">
                  {columns.map((column, index) => {
                    const content = column.render(row);
                    const classes = `px-3 ${cellY} ${
                      column.numeric ? "text-right fp-num" : "text-left"
                    }`;
                    return index === 0 ? (
                      <th key={column.key} scope="row" className={`${classes} font-normal`}>
                        {content}
                      </th>
                    ) : (
                      <td key={column.key} className={classes}>
                        {content}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
            {footer ? <tfoot className="bg-canvas font-medium">{footer}</tfoot> : null}
          </table>
        </>
      )}
    </section>
  );
}
