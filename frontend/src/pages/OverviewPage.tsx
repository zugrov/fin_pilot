import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  listCompanies,
  loadCashflowWithStatus,
  loadDashboard,
  loadForecast,
  loadReceivableAgingWithStatus,
  loadSources,
  loadUnclassifiedSummary,
} from "../api";
import { Shell } from "../components/Shell";
import { Amount } from "../components/system/Amount";
import { DonutChart } from "../components/system/DonutChart";
import { FreshnessLabel } from "../components/system/FreshnessLabel";
import { GroupedBarChart } from "../components/system/GroupedBarChart";
import { KpiCard } from "../components/system/KpiCard";
import { PeriodPicker } from "../components/system/PeriodPicker";
import { StatusChip } from "../components/system/StatusChip";
import { SECTIONS, sectionLabel } from "../lib/cashflow";
import { BUCKETS } from "../lib/receivable";
import { monthRangeInTimeZone } from "../lib/periodRange";
import { todayInTimeZone } from "../lib/receivable";
import { balanceLabel, isLoadedOnly, qualityNotes } from "../lib/overview";
import { revenueDisplay } from "../lib/revenue";
import { flowLabel } from "../lib/overview";
import { gapDisplay } from "../lib/forecast";

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

  // ОДДС за тот же период: секции нужны для сгруппированных столбцов на Обзоре.
  const cashflow = useQuery({
    queryKey: ["cashflow-overview", companyId, period.from, period.to],
    queryFn: () => loadCashflowWithStatus(companyId, period.from, period.to),
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

  // Секции ОДДС в фиксированном порядке: неизвестные коды — в конец.
  const cashflowSections = (cashflow.data?.sections ?? [])
    .slice()
    .sort((a, b) => {
      const indexA = SECTIONS.indexOf(a.code as (typeof SECTIONS)[number]);
      const indexB = SECTIONS.indexOf(b.code as (typeof SECTIONS)[number]);
      return (indexA === -1 ? SECTIONS.length : indexA) - (indexB === -1 ? SECTIONS.length : indexB);
    });

  const sectionBars = cashflowSections.map((section) => ({
    label: sectionLabel(section.code),
    values: [section.in, section.out],
  }));

  const receivableSlices = BUCKETS.map((code, index) => ({
    label: code === ">90" ? "Старше 90 дней" : code,
    value: agingData === undefined ? null : (bucketTotals[code] ?? null),
    color: `var(--fp-series-${(index % 6) + 1})`,
  }));

  // Прогноз: только существующий ряд points, без выдуманных данных.
  const forecastPoints = forecast.data?.points ?? [];
  const shownForecastPoints = forecastPoints.slice(0, 14);
  const forecastBars = shownForecastPoints.map((point) => ({
    label: `${point.date.slice(8, 10)}.${point.date.slice(5, 7)}`,
    values: [point.inflows, point.outflows],
  }));

  const freshness = {
    coverageThrough: cashSource?.coverage_through ?? null,
    completeness: dashboard.data === undefined ? "unavailable" : loadedOnly ? "preliminary" : "full",
    missingSource: sources.isSuccess && !cashSource,
  };

  return (
    <Shell
      title="Обзор"
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
            meta={
              <>
                {/* Строки ниже сохраняются дословно: их проверяет полигон. */}
                <div>
                  Начальный остаток:{" "}
                  {values.opening_balance === null ? (
                    "Нет начального остатка"
                  ) : (
                    <Amount value={values.opening_balance} align="left" />
                  )}
                </div>
                <div>Операций: {values.operation_count ?? "Нет данных"}</div>
              </>
            }
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
            valueText={
              gapAmount === null || gapAmount === "0.00"
                ? gapDisplay(gapAmount, forecast.data?.status ?? "")
                : undefined
            }
            caption={gapDate ? `Ожидается ${gapDate}` : "Разрыва не видно"}
            tone={gapAmount === null || gapAmount === "0.00" ? "neutral" : "outflow"}
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
          <GroupedBarChart
            title="Движение денег по секциям за период"
            data={sectionBars}
            series={[
              { name: "Поступления", color: "var(--fp-inflow)" },
              { name: "Списания", color: "var(--fp-outflow)" },
            ]}
            id="cf-sections"
          />
          <DonutChart
            title="Долги по срокам"
            data={receivableSlices}
            centerLabel="Всего долгов"
            centerValue={agingTotal}
            id="ar-donut"
          />
        </div>
      ) : null}

      {forecastBars.length > 0 ? (
        <div className="mb-6">
          <GroupedBarChart
            title="Прогноз: ожидаемые поступления и выплаты"
            data={forecastBars}
            series={[
              { name: "Ожидаемые поступления", color: "var(--fp-series-2)" },
              { name: "Ожидаемые выплаты", color: "var(--fp-series-3)" },
            ]}
            id="fc-bars"
            collapsible
          />
          {forecastPoints.length > shownForecastPoints.length ? (
            <p className="mt-1 text-note text-ink-subtle">
              Показаны первые {shownForecastPoints.length} дат прогноза из {forecastPoints.length}.
            </p>
          ) : null}
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
