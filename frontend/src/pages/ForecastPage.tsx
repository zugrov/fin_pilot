import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { listCompanies, loadForecast, loadGroupForecast } from "../api";
import { Shell } from "../components/Shell";
import { KpiCard } from "../components/system/KpiCard";
import { formatMoney } from "../lib/money";
import {
  closingLabel,
  companyDate,
  forecastCaption,
  forecastErrorText,
  gapDisplay,
  matchesSelection,
  unpaidLabel,
} from "../lib/forecast";

export function ForecastPage() {
  const [scenario, setScenario] = useState("base");
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [pickedDate, setPickedDate] = useState<string | null>(null);
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const list = companies.data?.companies ?? [];
  const preferred = sessionStorage.getItem("fp_company_id");
  const company =
    list.find((item) => item.id === pickedId) ??
    list.find((item) => item.id === preferred) ??
    list[0];
  const asOf = pickedDate ?? (company ? companyDate(company.timezone ?? "") : "");
  const forecast = useQuery({
    queryKey: ["forecast", company?.id, asOf, scenario],
    queryFn: () => loadForecast(company?.id ?? "", asOf, scenario),
    enabled: Boolean(company && asOf),
  });
  const group = useQuery({
    queryKey: ["group-forecast", asOf, scenario],
    queryFn: () => loadGroupForecast(asOf, scenario),
    enabled: Boolean(asOf),
  });
  const current = matchesSelection(forecast.data, company?.id, asOf) ? forecast.data : null;
  const point = current?.points.find((item) => item.date === current.gap_date);
  const outflows = (current?.contributions ?? []).filter((item) => item.direction === "out");

  return (
    <Shell title="Прогноз">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        {list.length > 0 ? (
          <label className="text-sm">
            Фирма
            <select
              className="mt-1 block rounded-control border px-3 py-1"
              value={company?.id ?? ""}
              onChange={(event) => setPickedId(event.target.value)}
            >
              {list.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="text-sm">
          Дата расчёта
          <input
            className="mt-1 block rounded-control border px-3 py-1"
            type="date"
            value={asOf}
            onChange={(event) => setPickedDate(event.target.value)}
          />
        </label>
        {["base", "conservative", "optimistic"].map((item) => (
          <button
            key={item}
            type="button"
            className="rounded-control border px-3 py-1"
            onClick={() => setScenario(item)}
          >
            {item}
          </button>
        ))}
      </div>
      {asOf ? <p className="mb-3 text-sm text-ink-muted">{forecastCaption(asOf)}</p> : null}
      {forecast.isLoading || forecast.isFetching ? <p>Загрузка</p> : null}
      {forecast.isError ? <p className="text-danger">{forecastErrorText()}</p> : null}
      {current && !forecast.isFetching && !forecast.isError ? (
        <>
          <div className="mb-4 grid gap-4 sm:grid-cols-2">
            <KpiCard
              title="Остаток на старт"
              value={current.opening}
              caption="на дату расчёта"
              chip={
                current.status === "preliminary"
                  ? { label: "Предварительно", tone: "warn" }
                  : { label: "Готово", tone: "ok" }
              }
              testId="forecast-opening"
            />
            <KpiCard
              title="Ближайший разрыв"
              value={current.gap_amount}
              caption={current.gap_date ?? "Разрыва не видно"}
              tone={current.gap_amount === null ? "neutral" : "outflow"}
              testId="forecast-gap"
            />
          </div>
          {current.gap_date && point ? (
            <p className="mb-3 text-sm text-ink-muted">
              {closingLabel(current.gap_date, point.closing)}
            </p>
          ) : null}
          {outflows.length > 0 ? (
            <section className="mb-6 rounded-card border border-line bg-surface p-card">
              <h2 className="mb-2 text-label text-ink-muted">Ожидаемые выплаты</h2>
              {outflows.map((item) => (
                <p key={`${item.date}-${item.amount}`} className="text-sm">
                  {unpaidLabel(item.amount, item.date)}
                </p>
              ))}
            </section>
          ) : null}
        </>
      ) : null}
      {group.isError ? <p className="text-danger">Группа не посчитана.</p> : null}
      {group.data && group.data.as_of === asOf && !group.isFetching && !group.isError ? (
        <section>
          <h2 className="mb-2 font-semibold">Фирмы</h2>
          <p className="mb-2 text-sm">
            Группа: {group.data.group_opening === null ? "нет данных" : formatMoney(group.data.group_opening)}
          </p>
          <ul className="space-y-2">
            {group.data.company_risks.map((item) => (
              <li key={item.company_id} className="rounded-control border bg-white p-3 text-sm">
                {gapDisplay(item.gap_amount, item.status)}
                {item.gap_date ? `, ${item.gap_date}` : ""}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </Shell>
  );
}
