import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  listCompanies,
  loadReceivableAgingWithStatus,
  type ReceivableAgingRow,
} from "../api";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
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

function heatClass(percent: string): string {
  const value = Number(percent.replace(",", "."));
  if (!Number.isFinite(value) || value <= 0) {
    return "bg-slate-50";
  }
  if (value < 15) {
    return "bg-amber-50";
  }
  if (value < 40) {
    return "bg-amber-100";
  }
  if (value < 70) {
    return "bg-amber-200";
  }
  return "bg-amber-300";
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
            className={`rounded-xl border p-3 ${heatClass(percent)}`}
          >
            <p className="text-xs text-slate-700">{bucketLabel(slice.code)}</p>
            <p className="mt-1 text-lg font-medium tabular-nums">{formatMoney(slice.total)}</p>
            <p className="text-sm text-slate-900 tabular-nums">{bucketPercentText(percent)}</p>
            <p className="mt-1 text-xs text-slate-700">{bucketHint(slice.code)}</p>
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
                <dt className="text-xs text-slate-600">Дата</dt>
                <dd>{row.recognition_date}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-600">Документ</dt>
                <dd className="break-all">{documentLabel(row.document)}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-600">Сумма</dt>
                <dd className="tabular-nums font-medium">{formatMoney(row.balance)}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-600">Корзина · дней</dt>
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
          <tr className="bg-slate-100 text-left">
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
    <Shell>
      <h1 className="mb-2 text-xl font-semibold">Дебиторка</h1>
      <p className="mb-4 text-sm text-slate-600">{debtBasisNote()}</p>

      <CompanyWritePicker
        listPhase={selection.listPhase}
        list={selection.list}
        value={selection.selectValue}
        needsPlaceholder={selection.needsPlaceholder}
        disabled={selection.pickerDisabled}
        onSelect={selection.onSelect}
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="text-sm">
          Дата среза
          <input
            className="mt-1 block rounded border px-3 py-1"
            type="date"
            value={asOf}
            onChange={(event) => {
              setAsOfTouched(true);
              setAsOf(event.target.value);
            }}
          />
        </label>
      </div>

      {!asOfValid && asOf ? (
        <p className="mb-4 text-red-700">Дата среза в формате ГГГГ-ММ-ДД.</p>
      ) : null}

      {!companyId && selection.listPhase === "ready" ? (
        <p className="mb-4 text-sm text-amber-800">Выберите фирму, чтобы посчитать долги.</p>
      ) : null}

      {report.isLoading ? <p className="mb-4">Загрузка отчёта…</p> : null}
      {report.isError ? (
        <p className="mb-4 text-red-700" role="alert">
          {receivableErrorText(report.error)}
        </p>
      ) : null}

      {current && !unavailable ? (
        <>
          <section className="mb-4 rounded-xl border bg-white p-4">
            <p className="text-sm text-slate-600">{asOfCaption(current.as_of)}</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">
              {formatMoney(current.total_balance)}
            </p>
            <p className="mt-1 text-sm text-slate-600">
              Столько покупатели должны вам на эту дату.
            </p>
            <p className="mt-3 text-sm text-slate-600">
              Состояние данных: <strong>{completenessLabel(current.completeness)}</strong>
            </p>
            <p className="mt-1 text-sm text-slate-600">{completenessNote(current.completeness)}</p>
          </section>

          {noRevenueSource ? (
            <div
              role="status"
              className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900"
            >
              {flagNotes(["missing_revenue_source"])[0]}
            </div>
          ) : null}

          {notes.length > 0 ? (
            <ul className="mb-4 list-inside list-disc text-sm text-slate-700">
              {notes.map((note, index) => (
                <li key={`${note}-${index}`}>{note}</li>
              ))}
            </ul>
          ) : null}

          <section className="mb-4">
            <h2 className="mb-2 text-sm font-medium text-slate-700">По срокам</h2>
            <BucketTiles totals={current.totals_by_bucket} total={current.total_balance} />
          </section>

          {truncated ? (
            <p className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              {truncatedNotice(500)}
            </p>
          ) : null}

          <section className="mb-4 rounded-xl border bg-white p-4">
            <h2 className="mb-2 text-sm font-medium text-slate-700">Долги покупателей</h2>
            {debtRows.length === 0 ? (
              <p className="text-sm text-slate-600">{emptyStateText()}</p>
            ) : (
              <DebtRows rows={debtRows} />
            )}
          </section>

          {orphanRows.length > 0 ? (
            <section className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-4">
              <h2 className="text-sm font-medium text-amber-900">{orphanTitle()}</h2>
              <p className="mt-1 text-sm text-amber-900">{orphanNote()}</p>
              <ul className="mt-2 space-y-1 text-sm text-amber-900">
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
            <section className="mb-4 rounded-xl border bg-white p-4">
              <h2 className="text-sm font-medium text-slate-700">{unallocatedTitle()}</h2>
              <p className="mt-1 text-sm text-slate-600">{unallocatedNote()}</p>
              <ul className="mt-2 space-y-1 text-sm">
                {unallocated.map((item) => (
                  <li key={item.cash_transaction_id} className="tabular-nums">
                    {item.business_date} · {item.document_number ?? "—"} · {item.label} ·{" "}
                    {formatMoney(item.amount)}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-sm text-slate-700">
                Всего без привязки:{" "}
                <strong className="tabular-nums">
                  {formatMoney(sumMoney(unallocated.map((item) => item.amount)))}
                </strong>
              </p>
            </section>
          ) : null}

          {bucketMismatch || rowsMismatch ? (
            <p className="mb-4 text-sm text-amber-800">
              Итог не совпал с суммой частей. Обновите страницу; если расхождение осталось —
              сообщите в поддержку.
            </p>
          ) : null}

          <p className="text-xs text-slate-500">
            Суммы показаны с НДС, по проведённым продажам. Оплата уменьшает долг только после
            привязки к продаже.
          </p>
        </>
      ) : null}

      {current && unavailable ? (
        <section className="mb-4 rounded-xl border bg-white p-4">
          <p className="text-sm font-medium">{completenessLabel(current.completeness)}</p>
          <p className="mt-1 text-sm text-slate-600">{completenessNote(current.completeness)}</p>
          {noRevenueSource ? (
            <p className="mt-2 text-sm text-slate-600">
              {flagNotes(["missing_revenue_source"])[0]}
            </p>
          ) : null}
        </section>
      ) : null}
    </Shell>
  );
}
