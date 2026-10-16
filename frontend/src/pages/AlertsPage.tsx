import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ackAlert, listCompanies, loadAlerts, recalculateAlerts } from "../api";
import { Shell } from "../components/Shell";
import { completenessCaption, savedCalculationCaption } from "../lib/alerts";
import { alertEmpty } from "../lib/budget";

export function AlertsPage() {
  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const companyId = companies.data?.companies[0]?.id;
  const alerts = useQuery({
    queryKey: ["alerts", companyId],
    queryFn: () => loadAlerts(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const ack = useMutation({
    mutationFn: (alertId: string) => ackAlert(alertId),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["alerts", companyId] });
    },
  });
  const recalc = useMutation({
    mutationFn: () => recalculateAlerts(companyId ?? ""),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["alerts", companyId] });
    },
  });
  const openCount = alerts.data?.alerts.filter((item) => item.status !== "resolved").length ?? 0;
  const completeness = completenessCaption(alerts.data?.completeness);

  return (
    <Shell>
      <h1 className="mb-4 text-xl font-semibold">Алерты</h1>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <p className="text-sm text-slate-600">
          {savedCalculationCaption(alerts.data?.report_date ?? null)}
        </p>
        {completeness ? <p className="text-sm text-slate-600">{completeness}</p> : null}
        <button
          type="button"
          className="rounded border px-3 py-1"
          disabled={!companyId || recalc.isPending}
          onClick={() => recalc.mutate()}
        >
          Пересчитать
        </button>
      </div>
      {recalc.isError ? <p className="mb-3 text-red-700">Не удалось пересчитать сигналы.</p> : null}
      {alerts.isLoading ? <p>Загрузка</p> : null}
      {alerts.isError ? <p className="text-red-700">Не удалось загрузить сигналы.</p> : null}
      {alerts.data ? (
        <p className="mb-3 text-sm">{alertEmpty(alerts.data.status, openCount)}</p>
      ) : null}
      <ul className="space-y-3">
        {alerts.data?.alerts
          .filter((item) => item.status !== "resolved")
          .map((item) => (
            <li key={item.id} className="rounded-xl border bg-white p-4">
              <p className="font-medium">
                {item.type}, {item.status}
              </p>
              <p className="text-sm text-slate-600">
                {Object.entries(item.evidence)
                  .map(([key, value]) => `${key}: ${value ?? "—"}`)
                  .join("; ")}
              </p>
              {item.status === "open" ? (
                <button
                  type="button"
                  className="mt-2 rounded border px-3 py-1"
                  onClick={() => ack.mutate(item.id)}
                >
                  Подтвердить
                </button>
              ) : null}
            </li>
          ))}
      </ul>
    </Shell>
  );
}
