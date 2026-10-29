import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listCompanies, loadCashflowWithStatus, type CashflowSection } from "../api";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import {
  cashflowErrorText,
  completenessLabel,
  completenessNote,
  drilldownNotice,
  emptyStateText,
  flagNotes,
  formatMoney,
  hasUnclassified,
  isDrilldownTruncated,
  isUnavailable,
  netOf,
  periodCaption,
  sectionHint,
  sectionLabel,
  sectionNetText,
  sumMoney,
  totalsMismatch,
} from "../lib/cashflow";
import { companyScopedData, useWritableCompanySelection } from "../lib/companySelection";
import { monthRangeInTimeZone, validatePeriod } from "../lib/periodRange";

function DrilldownPanel({ ids }: { ids: readonly string[] }) {
  return (
    <div className="rounded-card bg-canvas p-3">
      <p className="mb-2 text-xs text-ink-muted">Операций в группе: {ids.length}</p>
      {isDrilldownTruncated(ids) ? (
        <p className="mb-2 text-xs text-warn">{drilldownNotice()}</p>
      ) : null}
      <ul className="list-inside list-disc break-all text-xs text-ink">
        {ids.map((id) => (
          <li key={id}>{id}</li>
        ))}
      </ul>
    </div>
  );
}

function DrilldownToggle({
  ids,
  open,
  onToggle,
}: {
  ids: readonly string[];
  open: boolean;
  onToggle: () => void;
}) {
  if (ids.length === 0) {
    return null;
  }
  return (
    <button
      type="button"
      className="mt-2 rounded-control border px-2 py-1 text-xs"
      aria-expanded={open}
      onClick={onToggle}
    >
      {open ? "Скрыть операции" : `Показать операции (${ids.length})`}
    </button>
  );
}

function SectionCard({ section }: { section: CashflowSection }) {
  const [open, setOpen] = useState(false);
  const ids = section.transaction_ids ?? [];
  const hint = sectionHint(section.code);

  return (
    <li className="border-t py-3 first:border-t-0">
      <p className="font-medium">{sectionLabel(section.code)}</p>
      {hint ? <p className="mt-1 text-xs text-ink-muted">{hint}</p> : null}
      <dl className="mt-2 grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="text-xs text-ink-muted">Поступило</dt>
          <dd className="tabular-nums">{formatMoney(section.in)}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-muted">Списано</dt>
          <dd className="tabular-nums">{formatMoney(section.out)}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-muted">Итого</dt>
          <dd className="tabular-nums font-medium">{sectionNetText(section.in, section.out)}</dd>
        </div>
      </dl>
      <DrilldownToggle ids={ids} open={open} onToggle={() => setOpen((prev) => !prev)} />
      {open && ids.length > 0 ? (
        <div className="mt-2">
          <DrilldownPanel ids={ids} />
        </div>
      ) : null}
    </li>
  );
}

function SectionTableRow({ section }: { section: CashflowSection }) {
  const [open, setOpen] = useState(false);
  const ids = section.transaction_ids ?? [];
  const hint = sectionHint(section.code);

  return (
    <>
      <tr className="border-t align-top">
        <th scope="row" className="py-3 pr-3 pl-2 text-left font-normal">
          <span className="block font-medium">{sectionLabel(section.code)}</span>
          {hint ? <span className="mt-1 block text-xs text-ink-muted">{hint}</span> : null}
          <DrilldownToggle ids={ids} open={open} onToggle={() => setOpen((prev) => !prev)} />
        </th>
        <td className="py-3 pr-3 text-right tabular-nums">{formatMoney(section.in)}</td>
        <td className="py-3 pr-3 text-right tabular-nums">{formatMoney(section.out)}</td>
        <td className="py-3 pr-2 text-right tabular-nums">
          {sectionNetText(section.in, section.out)}
        </td>
      </tr>
      {open && ids.length > 0 ? (
        <tr className="bg-canvas">
          <td colSpan={4} className="px-2 py-3">
            <DrilldownPanel ids={ids} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

export function CashflowPage() {
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const selection = useWritableCompanySelection(companies);
  const { companyId, company } = selection;

  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");

  useEffect(() => {
    if (!company?.timezone || periodFrom) {
      return;
    }
    const range = monthRangeInTimeZone(company.timezone);
    setPeriodFrom(range.from);
    setPeriodTo(range.to);
  }, [company?.timezone, periodFrom]);

  const periodCheck =
    periodFrom && periodTo ? validatePeriod(periodFrom, periodTo) : { ok: true as const };
  const periodInvalid = !periodCheck.ok;

  const report = useQuery({
    queryKey: ["cashflow", companyId, periodFrom, periodTo],
    queryFn: () => loadCashflowWithStatus(companyId ?? "", periodFrom, periodTo),
    enabled: Boolean(companyId) && Boolean(periodFrom) && Boolean(periodTo) && !periodInvalid,
  });

  const current = companyScopedData(companyId, report.data?.company_id, report.data);
  const sections = current?.sections ?? [];
  const totalIn = current ? sumMoney(sections.map((item) => item.in)) : null;
  const totalOut = current ? sumMoney(sections.map((item) => item.out)) : null;
  const mismatch = current
    ? totalsMismatch(
        current.net_external,
        sections.map((item) => netOf(item.in, item.out)),
      )
    : false;
  const unavailable = current ? isUnavailable(current.completeness) : false;
  const unclassified = current ? hasUnclassified(current.quality_flags) : false;
  const notes = current ? flagNotes(current.quality_flags) : [];

  return (
    <Shell
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
            Период с
            <input
              className="mt-1 block min-h-tap rounded-control border border-line px-2 text-body fp-num"
              type="date"
              value={periodFrom}
              onChange={(event) => setPeriodFrom(event.target.value)}
            />
          </label>
          <label className="text-note text-ink-muted">
            по
            <input
              className="mt-1 block min-h-tap rounded-control border border-line px-2 text-body fp-num"
              type="date"
              value={periodTo}
              onChange={(event) => setPeriodTo(event.target.value)}
            />
          </label>
        </div>
      }
    >
      <h1 className="mb-2 text-title font-semibold">Движение денег</h1>
      <p className="mb-4 text-body text-ink-muted">
        Поступления и списания по счетам за период. Это движение денег, а не прибыль:
        прибыль считается отдельно, по выручке и расходам.
      </p>

      {periodInvalid ? <p className="mb-4 text-danger">{periodCheck.message}</p> : null}

      {!companyId && selection.listPhase === "ready" ? (
        <p className="mb-4 text-sm text-warn">Выберите фирму, чтобы построить отчёт.</p>
      ) : null}

      {report.isLoading ? <p className="mb-4">Загрузка отчёта…</p> : null}
      {report.isError ? (
        <p className="mb-4 text-danger" role="alert">
          {cashflowErrorText(report.error)}
        </p>
      ) : null}

      {current && !unavailable ? (
        <>
          <section className="mb-4 rounded-card border bg-white p-4">
            <p className="text-sm text-ink-muted">
              Состояние данных: <strong>{completenessLabel(current.completeness)}</strong>
            </p>
            <p className="mt-1 text-sm text-ink-muted">{completenessNote(current.completeness)}</p>
            <p className="mt-2 text-sm text-ink-muted">
              {periodCaption(current.date_from, current.date_to)}
            </p>
            <p className="text-sm text-ink-muted">Операций в отчёте: {current.external_count}</p>
          </section>

          {unclassified ? (
            <div
              role="status"
              className="mb-4 rounded-card border border-warn-line bg-warn-soft p-4 text-sm text-warn"
            >
              <p>
                Часть операций без категории — они попали в «Не разнесено по видам
                деятельности». Пока категории не заданы, отчёт остаётся предварительным.
              </p>
              <Link className="mt-2 inline-block underline" to="/classification">
                Перейти к классификации
              </Link>
            </div>
          ) : null}

          {notes.length > 0 ? (
            <ul className="mb-4 list-inside list-disc text-sm text-ink">
              {notes.map((note, index) => (
                <li key={`${note}-${index}`}>{note}</li>
              ))}
            </ul>
          ) : null}

          <section className="mb-2 rounded-card border bg-white p-4">
            <h2 className="mb-2 text-sm font-medium text-ink">По видам деятельности</h2>

            <ul className="sm:hidden">
              {sections.map((section) => (
                <SectionCard key={section.code} section={section} />
              ))}
            </ul>

            <table className="hidden w-full text-sm sm:table">
              <caption className="sr-only">
                Движение денег по видам деятельности за выбранный период
              </caption>
              <thead>
                <tr className="bg-canvas text-left">
                  <th scope="col" className="py-2 pr-3 pl-2">
                    Вид деятельности
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right">
                    Поступило
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right">
                    Списано
                  </th>
                  <th scope="col" className="py-2 pr-2 text-right">
                    Итого
                  </th>
                </tr>
              </thead>
              <tbody>
                {sections.map((section) => (
                  <SectionTableRow key={section.code} section={section} />
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t bg-canvas font-medium">
                  <th scope="row" className="py-3 pr-3 pl-2 text-left">
                    Итого по всем секциям
                  </th>
                  <td className="py-3 pr-3 text-right tabular-nums">{formatMoney(totalIn)}</td>
                  <td className="py-3 pr-3 text-right tabular-nums">{formatMoney(totalOut)}</td>
                  <td className="py-3 pr-2 text-right tabular-nums">
                    {formatMoney(current.net_external)}
                  </td>
                </tr>
              </tfoot>
            </table>

            <dl className="mt-3 grid grid-cols-3 gap-2 border-t pt-3 text-sm sm:hidden">
              <div>
                <dt className="text-xs text-ink-muted">Поступило всего</dt>
                <dd className="tabular-nums">{formatMoney(totalIn)}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-muted">Списано всего</dt>
                <dd className="tabular-nums">{formatMoney(totalOut)}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-muted">Итого</dt>
                <dd className="tabular-nums font-medium">{formatMoney(current.net_external)}</dd>
              </div>
            </dl>
          </section>

          {mismatch ? (
            <p className="mb-4 text-sm text-warn">
              Итог по секциям не совпал с общим итогом отчёта. Обновите страницу; если
              расхождение осталось — сообщите в поддержку.
            </p>
          ) : null}

          <p className="text-xs text-ink-subtle">
            Переводы между своими счетами в итог не входят. Суммы — по проведённым операциям.
          </p>
        </>
      ) : null}

      {current && unavailable ? (
        <section className="mb-4 rounded-card border bg-white p-4">
          <p className="text-sm font-medium">{completenessLabel(current.completeness)}</p>
          <p className="mt-1 text-sm text-ink-muted">{completenessNote(current.completeness)}</p>
          <p className="mt-2 text-sm text-ink-muted">{emptyStateText()}</p>
          <Link className="mt-2 inline-block underline" to="/import">
            Перейти к импорту
          </Link>
        </section>
      ) : null}
    </Shell>
  );
}
