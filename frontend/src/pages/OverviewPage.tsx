import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  listCompanies,
  loadDashboard,
  loadForecast,
  loadReceivableAgingWithStatus,
  loadSources,
  loadUnclassifiedSummary,
} from "../api";
import { Shell } from "../components/Shell";
import { Amount } from "../components/system/Amount";
import { BarChart } from "../components/system/BarChart";
import { FreshnessLabel } from "../components/system/FreshnessLabel";
import { KpiCard } from "../components/system/KpiCard";
import { PeriodPicker } from "../components/system/PeriodPicker";
import { StatusChip } from "../components/system/StatusChip";
import { BUCKETS } from "../lib/receivable";
import { monthRangeInTimeZone } from "../lib/periodRange";
import { todayInTimeZone } from "../lib/receivable";
import { balanceLabel, isLoadedOnly, qualityNotes } from "../lib/overview";
import { revenueDisplay } from "../lib/revenue";
import { flowLabel } from "../lib/overview";

/** Сумма поступлений и списаний двух месяцев не складывается: показываем как есть. */
export function OverviewPage() {  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const [pickedCompanyId, setPickedCompanyId] = useState<string | null>(null);
  const preferred = pickedCompanyId ?? sessionStorage.getItem("fp_company_id");
  const company = companies.data?.companies.find((item) => item.id === preferred)
    ?? companies.data?.companies[0];
  const companyId = company?.id ?? "";

  const timezone = company?.timezone ?? "Europe/Moscow";
  const today = todayInTimeZone(timezone);
  const [period, setPeriod] = useState(() => monthRangeInTimeZone(timezone));

  const dashboard = useQuery({
    queryKey: ["dashboard", companyId, period.from, period.to],
    queryFn: () => loadDashboard(companyId),
    enabled: Boolean(companyId),
  });

  const aging = useQuery({
    queryKey: ["receivable-aging", companyId, today],
    queryFn: () => loadReceivableAgingWithStatus(companyId, today),
    enabled: Boolean(companyId),
  });

  const sources = useQuery({
    queryKey: ["sources", companyId],
    queryFn: () => loadSources(companyId),
    enabled: Boolean(companyId),
  });

  const unclassified = useQuery({
    queryKey: ["unclassified-summary", companyId, period.from, period.to],
    queryFn: () => loadUnclassifiedSummary(companyId, period.from, period.to),
    enabled: Boolean(companyId),
  });

  const forecast = useQuery({
    queryKey: ["forecast", companyId, today],
    queryFn: () => loadForecast(companyId, today),
    enabled: Boolean(companyId),
  });

  const values = dashboard.data?.values;
  const flags = dashboard.data?.quality_flags ?? [];
  const notes = qualityNotes(flags);
  const loadedOnly = isLoadedOnly(flags);
  const periodFrom = dashboard.data?.date_from ?? period.from;
  const periodTo = dashboard.data?.date_to ?? period.to;

  const cashSource = (sources.data?.sources ?? []).find((item) => item.dataset === "cash");
  const revenueSource = (sources.data?.sources ?? []).find((item) => item.dataset === "revenue");

  const agingData = aging.data;
  // «Нет данных» вместо нуля: пустой отчёт без источника продаж — не нулевой долг.
  const agingUnavailable = agingData !== undefined && agingData.completeness === "unavailable";
  const agingTotal = agingUnavailable ? null : (agingData?.total_balance ?? null);
  const bucketTotals = agingUnavailable ? {} : (agingData?.totals_by_bucket ?? {});
  const over30 = BUCKETS.slice(1).reduce((acc, code) => {
    const raw = bucketTotals[code];
    if (!raw) {
      return acc;
    }
    const num = Number(raw.replace(/\s/g, "").replace(",", "."));
    return Number.isFinite(num) ? acc + num : acc;
  }, 0);
  const over30Text = agingTotal === null ? null : over30.toFixed(2);

  const unclassifiedCount =
    unclassified.data === undefined
      ? null
      : unclassified.data.in.count + unclassified.data.out.count;

  const gapAmount = forecast.data?.gap_amount ?? null;
  const gapDate = forecast.data?.gap_date ?? null;

  const cashflowBars = (dashboard.data?.values ?? null)
    ? [
        { label: "Поступления", value: values?.cash_in ?? null },
        { label: "Списания", value: values?.cash_out ?? null },
        { label: "Чистое движение", value: values?.net_cash_flow ?? null },
      ]
    : [];

  const receivableBars = BUCKETS.map((code) => ({
    label: code === ">90" ? "> 90" : code,
    // Если дебиторка недоступна — null, а не ноль: диаграмма покажет пустоту.
    value: agingData === undefined ? null : (bucketTotals[code] ?? null),
  }));

  const freshness = {
    coverageThrough: cashSource?.coverage_through ?? null,
    completeness: dashboard.data === undefined ? "unavailable" : loadedOnly ? "preliminary" : "full",
    missingSource: sources.isSuccess && !cashSource,
  };

  return (
    <Shell
      header={
        <div className="flex flex-wrap items-center gap-3">
          {companies.data && companies.data.companies.length > 1 ? (
            <label className="text-note text-ink-muted">
              Фирма
              <select
                className="ml-2 min-h-tap rounded-control border border-line px-2 text-body"
                value={companyId}
                onChange={(event) => {
                  // Без перезагрузки страницы: смена фирмы инвалидирует только запросы.
                  sessionStorage.setItem("fp_company_id", event.target.value);
                  setPickedCompanyId(event.target.value);
                }}
              >
                {companies.data.companies.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <PeriodPicker
            from={period.from}
            to={period.to}
            today={today}
            onChange={setPeriod}
          />
          <FreshnessLabel {...freshness} />
        </div>
      }
    >
      <h1 className="mb-4 text-title">Обзор</h1>

      {companies.isLoading || dashboard.isLoading ? <p className="mb-4">Загрузка</p> : null}
      {companies.isError || dashboard.isError ? (
        <p className="mb-4 text-body text-danger">Не удалось загрузить обзор. Проверьте вход.</p>
      ) : null}
      {companies.data && companies.data.companies.length === 0 ? (
        <p className="text-body">Нет фирмы. Создайте её в тарифе после оплаты.</p>
      ) : null}

      {values ? (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            title="Деньги на счетах"
            value={values.cash_total}
            caption={balanceLabel(dashboard.data?.as_of ?? "")}
            tone={values.cash_total === null ? "warn" : "info"}
            testId="kpi-cash-total"
            detail={
              <>
                <div>
                  {flowLabel("Поступления", periodFrom, periodTo, loadedOnly)}:{" "}
                  <Amount value={values.cash_in} align="left" />
                </div>
                <div>
                  {flowLabel("Выплаты", periodFrom, periodTo, loadedOnly)}:{" "}
                  <Amount value={values.cash_out} align="left" />
                </div>
                <div>
                  Чистое движение: <Amount value={values.net_cash_flow} align="left" />
                </div>
                {/* Строки ниже сохраняются дословно: их проверяет полигон. */}
                <div>
                  Начальный остаток: {values.opening_balance ?? "Нет начального остатка"}
                </div>
                <div>Операций: {values.operation_count ?? "Нет данных"}</div>
              </>
            }
            action={<Link to="/cashflow">О движении денег</Link>}
          />

          <KpiCard
            title="Дебиторка"
            value={agingTotal}
            caption="Сколько покупатели должны вам"
            tone="warn"
            chip={
              agingData === undefined || agingUnavailable
                ? agingUnavailable
                  ? { label: "Нет данных", tone: "unavailable" as const }
                  : undefined
                : {
                    label: agingData.completeness === "full" ? "Полно" : "Предварительно",
                    tone: agingData.completeness === "full" ? ("ok" as const) : ("warn" as const),
                  }
            }
            detail={
              <div>
                Старше 30 дней: <Amount value={over30Text} align="left" />{" "}
                {agingTotal !== null ? (
                  <span className="text-note text-ink-subtle">
                    ({over30Text === null || Number(agingTotal) === 0 ? "0" : Math.round((over30 / Number(agingTotal)) * 100)} %)
                  </span>
                ) : null}
              </div>
            }
            action={<Link to="/receivables">О долгах покупателей</Link>}
          />

          <KpiCard
            title="Неразнесённые операции"
            value={null}
            valueText={unclassifiedCount === null ? null : String(unclassifiedCount)}
            caption="Без категории за период"
            tone={unclassifiedCount ? "warn" : "neutral"}
            chip={
              unclassifiedCount
                ? { label: "Требуют внимания", tone: "warn" }
                : { label: "Разобрано", tone: "ok" }
            }
            action={<Link to="/classification">Разобрать без категории</Link>}
          />

          <KpiCard
            title="Ближайший разрыв"
            value={gapAmount}
            caption={gapDate ? `Ожидается ${gapDate}` : "Разрыва не видно"}
            tone={gapAmount === null ? "neutral" : "outflow"}
            detail={
              forecast.data === undefined ? (
                <span className="text-note text-ink-subtle">Прогноз не рассчитан</span>
              ) : null
            }
            action={<Link to="/forecast">Разрыв и сроки</Link>}
          />
        </div>
      ) : null}

      {values ? (
        <div className="mb-6 grid gap-4 lg:grid-cols-2">
          <BarChart title="Движение денег за период" data={cashflowBars} id="cf" />
          <BarChart title="Долги по срокам" data={receivableBars} id="ar" />
        </div>
      ) : null}

      {values ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <section className="rounded-card border border-line bg-surface p-card">
            <h2 className="text-label text-ink-muted">Выручка</h2>
            <p className="mt-2 text-body">
              {revenueDisplay(values.revenue, dashboard.data?.revenue_label ?? "")}
            </p>
          </section>

          <section className="rounded-card border border-line bg-surface p-card">
            <h2 className="text-label text-ink-muted">Состояние данных</h2>
            <ul className="mt-2 space-y-1 text-body text-ink-muted">
              <li>
                Источник денег:{" "}
                {cashSource ? (
                  <StatusChip tone="ok">подключён</StatusChip>
                ) : sources.isSuccess ? (
                  <StatusChip tone="warn">не подключён</StatusChip>
                ) : (
                  "—"
                )}
              </li>
              <li>
                Источник выручки:{" "}
                {revenueSource ? (
                  <StatusChip tone="ok">подключён</StatusChip>
                ) : sources.isSuccess ? (
                  <StatusChip tone="warn">не подключён</StatusChip>
                ) : (
                  "—"
                )}
              </li>
            </ul>
            {notes.map((note) => (
              <p key={note} className="mt-2 text-body text-warn">
                {note}
              </p>
            ))}
          </section>
        </div>
      ) : null}
    </Shell>
  );
}
