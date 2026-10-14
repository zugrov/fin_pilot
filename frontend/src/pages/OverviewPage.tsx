import { useQuery } from "@tanstack/react-query";

import { listCompanies, loadDashboard } from "../api";
import { Shell } from "../components/Shell";
import { revenueDisplay } from "../lib/revenue";

export function OverviewPage() {
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const companyId = companies.data?.companies[0]?.id;
  const dashboard = useQuery({
    queryKey: ["dashboard", companyId],
    queryFn: () => loadDashboard(companyId ?? ""),
    enabled: Boolean(companyId),
  });

  return (
    <Shell>
      <h1 className="mb-4 text-xl font-semibold">Обзор</h1>
      {companies.isLoading || dashboard.isLoading ? <p>Загрузка</p> : null}
      {companies.isError || dashboard.isError ? (
        <p className="text-red-700">Не удалось загрузить обзор. Проверьте вход.</p>
      ) : null}
      {!companies.isLoading && companies.data?.companies.length === 0 ? (
        <p>Нет фирмы. Создайте её в тарифе после оплаты.</p>
      ) : null}
      {dashboard.data ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <section className="rounded-xl border bg-white p-4">
            <h2 className="text-sm text-slate-600">Деньги</h2>
            <p className="text-2xl">{dashboard.data.values.cash_total ?? "Нет остатка"}</p>
          </section>
          <section className="rounded-xl border bg-white p-4">
            <h2 className="text-sm text-slate-600">Выручка</h2>
            <p className="text-2xl">
              {revenueDisplay(dashboard.data.values.revenue, dashboard.data.revenue_label)}
            </p>
            <p className="mt-2 text-sm text-slate-600">
              Поступления: {dashboard.data.values.cash_total ?? "нет данных"}
            </p>
          </section>
        </div>
      ) : null}
    </Shell>
  );
}
