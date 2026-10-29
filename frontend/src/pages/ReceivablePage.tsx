import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  listCompanies,
  loadReceivableAgingWithStatus,
  type ReceivableAgingRow,
} from "../api";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import { KpiCard } from "../components/system/KpiCard";
import { StatusChip } from "../components/system/StatusChip";
import { companyScopedData, useWritableCompanySelection } from "../lib/companySelection";
import { formatMoney, sumMoney, toCents } from "../lib/money";
import {
  ageDaysLabel,
  asOfCaption,
  BUCKETS,
  bucketHint,
  bucketLabel,
  bucketPercentText,
  bucketShares,
  completenessLabel,
  completenessNote,
  counterpartyLabel,
  debtBasisNote,
  documentLabel,
  emptyStateText,
  flagNotes,
  hasMissingRevenueSource,
  isRowsTruncated,
  isUnavailable,
  orphanNote,
  orphanTitle,
  receivableErrorText,
  todayInTimeZone,
  truncatedNotice,
  unallocatedNote,
  unallocatedTitle,
} from "../lib/receivable";

/* Ступени тепловой карты: различаются рамкой и текстом, не только заливкой
   (4 ступени с шагом 3:1 физически невозможны, см. lib/palette.test.ts). */
const HEAT_CLASS = [
  "bg-[color:var(--fp-heat-1)] text-ink border-[color:var(--fp-heat-border-1)]",
  "bg-[color:var(--fp-heat-2)] text-ink border-[color:var(--fp-heat-border-2)]",
  "bg-[color:var(--fp-heat-3)] text-surface border-[color:var(--fp-heat-border-3)]",
  "bg-[color:var(--fp-heat-4)] text-surface border-[color:var(--fp-heat-border-4)]",
];

function heatClass(percent: string): string {
  const value = Number(percent.replace(",", "."));
  if (!Number.isFinite(value) || value <= 0) {
    return "bg-canvas border-line";
  }
  if (value < 15) {
    return HEAT_CLASS[0];
  }
  if (value < 40) {
    return HEAT_CLASS[1];
  }
  if (value < 70) {
    return HEAT_CLASS[2];
  }
  return HEAT_CLASS[3];
}

function BucketTiles({
  totals,
  total,
}: {
  totals: Record<string, string>;
  total: string;
}) {
  const slices = useMemo(
    () => BUCKETS.map((code) => ({ code, total: totals[code] ?? null })),
    [totals],
  );
  const shares = useMemo(() => bucketShares(slices, total), [slices, total]);

  return (
    <ul className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {slices.map((slice, index) => {
        const percent = shares[index]?.percent ?? "0";
        return (
          <li
            key={slice.code}
            data-testid={`bucket-${slice.code}`}
            className={`rounded-card border p-3 ${heatClass(percent)}`}
          >
            <p className="text-xs text-ink">{bucketLabel(slice.code)}</p>
            <p className="mt-1 text-lg font-medium tabular-nums">{formatMoney(slice.total)}</p>
            <p className="text-sm text-ink tabular-nums">{bucketPercentText(percent)}</p>
            <p className="mt-1 text-xs text-ink">{bucketHint(slice.code)}</p>
          </li>
        );
      })}
    </ul>
  );
}

function DebtRows({ rows }: { rows: readonly ReceivableAgingRow[] }) {
  return (
    <>
      <ul className="sm:hidden" data-testid="debt-cards">
        {rows.map((row, index) => (
          <li key={`${row.document.external_id ?? index}`} className="border-t py-3 first:border-t-0">
            <p className="font-medium">
              {row.counterparty === null || !row.counterparty.name
                ? "Контрагент не указан"
                : counterpartyLabel(row.counterparty)}
            </p>
            <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="text-xs text-ink-muted">Дата</dt>
                <dd>{row.recognition_date}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-muted">Документ</dt>
                <dd className="break-all">{documentLabel(row.document)}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-muted">Сумма</dt>
                <dd className="tabular-nums font-medium">{formatMoney(row.balance)}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-muted">Корзина · дней</dt>
                <dd>
                  {bucketLabel(row.bucket)} · {ageDaysLabel(row.age_days)}
                </dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>

      <table className="hidden w-full text-sm sm:table" data-testid="debt-table">
        <caption className="sr-only">
          Задолженность покупателей: строки с датой, контрагентом, документом, суммой и сроком
        </caption>
        <thead>
          <tr className="bg-canvas text-left">
            <th scope="col" className="py-2 pr-3 pl-2">
              Дата
            </th>
            <th scope="col" className="py-2 pr-3">
              Контрагент
            </th>
            <th scope="col" className="py-2 pr-3">
              Документ
            </th>
            <th scope="col" className="py-2 pr-3 text-right">
              Сумма
            </th>
            <th scope="col" className="py-2 pr-3">
              Корзина
            </th>
            <th scope="col" className="py-2 pr-2 text-right">
              Дней
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.document.external_id ?? index}`} className="border-t align-top">
              <td className="py-2 pr-3 pl-2 whitespace-nowrap">{row.recognition_date}</td>
              <th scope="row" className="py-2 pr-3 text-left font-normal">
                {counterpartyLabel(row.counterparty)}
              </th>
              <td className="py-2 pr-3 break-all">{documentLabel(row.document)}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{formatMoney(row.balance)}</td>
              <td className="py-2 pr-3">{bucketLabel(row.bucket)}</td>
              <td className="py-2 pr-2 text-right tabular-nums">{ageDaysLabel(row.age_days)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function ReceivablePage() {
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const selection = useWritableCompanySelection(companies);
  const { companyId, company } = selection;

  const [asOf, setAsOf] = useState("");
  const [asOfTouched, setAsOfTouched] = useState(false);

  useEffect(() => {
    if (asOfTouched || asOf || !companyId) {
      return;
    }
    const today = todayInTimeZone(company?.timezone ?? "Europe/Moscow");
    setAsOf(today);
  }, [company?.timezone, companyId, asOf, asOfTouched]);

  const asOfValid = /^\d{4}-\d{2}-\d{2}$/.test(asOf);

  const report = useQuery({
    queryKey: ["receivable-aging", companyId, asOf],
    queryFn: () => loadReceivableAgingWithStatus(companyId ?? "", asOf),
    enabled: Boolean(companyId) && asOfValid,
  });

  const current = companyScopedData(companyId, report.data?.company_id, report.data);
  const rows = current?.rows ?? [];
  const total = current?.total_balance ?? null;
  const bucketTotals = current
    ? BUCKETS.map((code) => current.totals_by_bucket[code] ?? null)
    : [];
  const rowSum = current ? sumMoney(rows.map((row) => row.balance)) : null;
  const bucketsSum = current ? sumMoney(bucketTotals) : null;

  const bucketMismatch =
    total !== null && bucketsSum !== null && toCents(total) !== toCents(bucketsSum);
  const rowsMismatch =
    total !== null && rowSum !== null && toCents(total) !== toCents(rowSum);

  const unavailable = current ? isUnavailable(current.completeness) : false;
  const noRevenueSource = current ? hasMissingRevenueSource(current.quality_flags) : false;
  const notes = current ? flagNotes(current.quality_flags) : [];
  const orphanRows = rows.filter((row) => row.orphan_return);
  const debtRows = rows.filter((row) => !row.orphan_return);
  const unallocated = current?.unallocated_receipts ?? [];
  const truncated = current ? isRowsTruncated(rows, current.rows_truncated) : false;

  return (
    <Shell
      title="Дебиторка"
      header={
        <div className="flex flex-wrap items-end gap-3">
          <CompanyWritePicker
            listPhase={selection.listPhase}
            list={selection.list}
            value={selection.selectValue}
            needsPlaceholder={selection.needsPlaceholder}
            disabled={selection.pickerDisabled}
            onSelect={selection.onSelect}
          />
          <label className="text-note text-ink-muted">
            Дата среза
            <input
              className="mt-1 block min-h-tap rounded-control border border-line px-2 text-body fp-num"
              type="date"
              value={asOf}
              onChange={(event) => {
                setAsOfTouched(true);
                setAsOf(event.target.value);
              }}
            />
          </label>
        </div>
      }
    >
      <p className="mb-4 text-body text-ink-muted">{debtBasisNote()}</p>

      {!asOfValid && asOf ? (
        <p className="mb-4 text-danger">Дата среза в формате ГГГГ-ММ-ДД.</p>
      ) : null}

      {!companyId && selection.listPhase === "ready" ? (
        <p className="mb-4 text-sm text-warn">Выберите фирму, чтобы посчитать долги.</p>
      ) : null}

      {report.isLoading ? <p className="mb-4">Загрузка отчёта…</p> : null}
      {report.isError ? (
        <p className="mb-4 text-danger" role="alert">
          {receivableErrorText(report.error)}
        </p>
      ) : null}

      {current && !unavailable ? (
        <>
          <div className="mb-4 grid gap-4 sm:grid-cols-2">
            <KpiCard
              title="Всего долгов"
              value={current.total_balance}
              caption="Столько покупатели должны вам на эту дату."
              tone="warn"
              testId="receivable-total"
            />
            <section className="rounded-card border border-line bg-surface p-card shadow-card">
              <h2 className="text-label text-ink-muted">Состояние данных</h2>
              <p className="mt-2 text-body">
                <StatusChip tone={current.completeness === "full" ? "ok" : "warn"}>
                  {completenessLabel(current.completeness)}
                </StatusChip>
              </p>
              <p className="mt-2 text-body text-ink-muted">{completenessNote(current.completeness)}</p>
              <p className="mt-2 text-note text-ink-subtle">{asOfCaption(current.as_of)}</p>
            </section>
          </div>

          {noRevenueSource ? (
            <div
              role="status"
              className="mb-4 rounded-card border border-warn-line bg-warn-soft p-4 text-sm text-warn"
            >
              {flagNotes(["missing_revenue_source"])[0]}
            </div>
          ) : null}

          {notes.length > 0 ? (
            <ul className="mb-4 list-inside list-disc text-sm text-ink">
              {notes.map((note, index) => (
                <li key={`${note}-${index}`}>{note}</li>
              ))}
            </ul>
          ) : null}

          <section className="mb-4">
            <h2 className="mb-2 text-sm font-medium text-ink">По срокам</h2>
            <BucketTiles totals={current.totals_by_bucket} total={current.total_balance} />
          </section>

          {truncated ? (
            <p className="mb-4 rounded-card border border-warn-line bg-warn-soft p-3 text-sm text-warn">
              {truncatedNotice(500)}
            </p>
          ) : null}

          <section className="mb-4 rounded-card border bg-white p-4">
            <h2 className="mb-2 text-sm font-medium text-ink">Долги покупателей</h2>
            {debtRows.length === 0 ? (
              <p className="text-sm text-ink-muted">{emptyStateText()}</p>
            ) : (
              <DebtRows rows={debtRows} />
            )}
          </section>

          {orphanRows.length > 0 ? (
            <section className="mb-4 rounded-card border border-warn-line bg-warn-soft p-4">
              <h2 className="text-sm font-medium text-warn">{orphanTitle()}</h2>
              <p className="mt-1 text-sm text-warn">{orphanNote()}</p>
              <ul className="mt-2 space-y-1 text-sm text-warn">
                {orphanRows.map((row, index) => (
                  <li key={`orphan-${row.document.external_id ?? index}`} className="tabular-nums">
                    {row.recognition_date} · {counterpartyLabel(row.counterparty)} ·{" "}
                    {documentLabel(row.document)} · {formatMoney(row.balance)}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {unallocated.length > 0 ? (
            <section className="mb-4 rounded-card border bg-white p-4">
              <h2 className="text-sm font-medium text-ink">{unallocatedTitle()}</h2>
              <p className="mt-1 text-sm text-ink-muted">{unallocatedNote()}</p>
              <ul className="mt-2 space-y-1 text-sm">
                {unallocated.map((item) => (
                  <li key={item.cash_transaction_id} className="tabular-nums">
                    {item.business_date} · {item.document_number ?? "—"} · {item.label} ·{" "}
                    {formatMoney(item.amount)}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-sm text-ink">
                Всего без привязки:{" "}
                <strong className="tabular-nums">
                  {formatMoney(sumMoney(unallocated.map((item) => item.amount)))}
                </strong>
              </p>
            </section>
          ) : null}

          {bucketMismatch || rowsMismatch ? (
            <p className="mb-4 text-sm text-warn">
              Итог не совпал с суммой частей. Обновите страницу; если расхождение осталось —
              сообщите в поддержку.
            </p>
          ) : null}

          <p className="text-xs text-ink-subtle">
            Суммы показаны с НДС, по проведённым продажам. Оплата уменьшает долг только после
            привязки к продаже.
          </p>
        </>
      ) : null}

      {current && unavailable ? (
        <section className="mb-4 rounded-card border bg-white p-4">
          <p className="text-sm font-medium">{completenessLabel(current.completeness)}</p>
          <p className="mt-1 text-sm text-ink-muted">{completenessNote(current.completeness)}</p>
          {noRevenueSource ? (
            <p className="mt-2 text-sm text-ink-muted">
              {flagNotes(["missing_revenue_source"])[0]}
            </p>
          ) : null}
        </section>
      ) : null}
    </Shell>
  );
}
