import { useQuery } from "@tanstack/react-query";

import { listCompanies, loadDashboard } from "../api";
import { Shell } from "../components/Shell";
import {
  balanceLabel,
  cashAmount,
  flowLabel,
  isLoadedOnly,
  qualityNotes,
} from "../lib/overview";
import { revenueDisplay } from "../lib/revenue";

export function OverviewPage() {
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const preferred = sessionStorage.getItem("fp_company_id");
  const companyId =
    companies.data?.companies.find((item) => item.id === preferred)?.id ??
    companies.data?.companies[0]?.id;
  const dashboard = useQuery({
    queryKey: ["dashboard", companyId],
    queryFn: () => loadDashboard(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const values = dashboard.data?.values;
  const flags = dashboard.data?.quality_flags ?? [];
  const notes = qualityNotes(flags);
  const loadedOnly = isLoadedOnly(flags);
  const periodFrom = dashboard.data?.date_from ?? "";
  const periodTo = dashboard.data?.date_to ?? "";

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
      {dashboard.data && values ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <section className="rounded-xl border bg-white p-4">
            <h2 className="text-sm text-slate-600">Деньги</h2>
            <p className="text-sm text-slate-600">{balanceLabel(dashboard.data.as_of)}</p>
            <p className="text-2xl">{cashAmount(values.cash_total, "Нет остатка")}</p>
            <p className="mt-2 text-sm">
              Начальный остаток: {cashAmount(values.opening_balance, "Нет начального остатка")}
            </p>
            <p className="mt-2 text-sm">
              {flowLabel("Поступления", periodFrom, periodTo, loadedOnly)}:{" "}
              {cashAmount(values.cash_in, "Нет данных")}
            </p>
            <p className="text-sm">
              {flowLabel("Выплаты", periodFrom, periodTo, loadedOnly)}:{" "}
              {cashAmount(values.cash_out, "Нет данных")}
            </p>
            <p className="text-sm">
              {flowLabel("Чистое движение", periodFrom, periodTo, loadedOnly)}:{" "}
              {cashAmount(values.net_cash_flow, "Нет данных")}
            </p>
            <p className="text-sm">
              Операций: {values.operation_count ?? "Нет данных"}
            </p>
            {notes.map((note) => (
              <p key={note} className="mt-2 text-sm text-amber-800">
                {note}
              </p>
            ))}
          </section>
          <section className="rounded-xl border bg-white p-4">
            <h2 className="text-sm text-slate-600">Выручка</h2>
            <p className="text-2xl">
              {revenueDisplay(values.revenue, dashboard.data.revenue_label)}
            </p>
          </section>
        </div>
      ) : null}
    </Shell>
  );
}
