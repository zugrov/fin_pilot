import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { listCompanies, loadForecast, loadGroupForecast } from "../api";
import { Shell } from "../components/Shell";
import { gapDisplay } from "../lib/forecast";

export function ForecastPage() {
  const [scenario, setScenario] = useState("base");
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const companyId = companies.data?.companies[0]?.id;
  const forecast = useQuery({
    queryKey: ["forecast", companyId, scenario],
    queryFn: () => loadForecast(companyId ?? "", scenario),
    enabled: Boolean(companyId),
  });
  const group = useQuery({
    queryKey: ["group-forecast", scenario],
    queryFn: () => loadGroupForecast(scenario),
  });

  return (
    <Shell>
      <h1 className="mb-4 text-xl font-semibold">Прогноз</h1>
      <div className="mb-4 flex flex-wrap gap-2">
        {["base", "conservative", "optimistic"].map((item) => (
          <button key={item} type="button" className="rounded border px-3 py-1" onClick={() => setScenario(item)}>
            {item}
          </button>
        ))}
      </div>
      {forecast.isLoading ? <p>Загрузка</p> : null}
      {forecast.isError ? <p className="text-red-700">Не удалось посчитать прогноз.</p> : null}
      {forecast.data ? (
        <section className="mb-6 rounded-xl border bg-white p-4">
          <p className="text-sm text-slate-600">
            {forecast.data.status === "preliminary" ? "Предварительно" : "Готово"}
          </p>
          <p className="text-xl font-semibold">
            {gapDisplay(forecast.data.gap_amount, forecast.data.status)}
          </p>
          {forecast.data.gap_date ? <p className="text-sm">Дата: {forecast.data.gap_date}</p> : null}
          <p className="text-sm">Остаток на старт: {forecast.data.opening ?? "нет данных"}</p>
        </section>
      ) : null}
      {group.isError ? <p className="text-red-700">Группа не посчитана.</p> : null}
      {group.data ? (
        <section>
          <h2 className="mb-2 font-semibold">Фирмы</h2>
          <p className="mb-2 text-sm">
            Группа: {group.data.group_opening ?? "нет данных"}
          </p>
          <ul className="space-y-2">
            {group.data.company_risks.map((item) => (
              <li key={item.company_id} className="rounded border bg-white p-3 text-sm">
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
