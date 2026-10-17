import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ackAlert, listCompanies, loadAlerts, recalculateAlerts } from "../api";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import { alertsRecalcTarget, companyScopedData, useWritableCompanySelection } from "../lib/companySelection";
import { completenessCaption, savedCalculationCaption } from "../lib/alerts";
import { alertEmpty } from "../lib/budget";

export function AlertsPage() {
  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const selection = useWritableCompanySelection(companies);
  const { companyId } = selection;
  const alerts = useQuery({
    queryKey: ["alerts", companyId],
    queryFn: () => loadAlerts(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const alertPayload = companyScopedData(companyId, companyId ?? undefined, alerts.data);
  const ack = useMutation({
    mutationFn: (alertId: string) => ackAlert(alertId),
    onSuccess: async () => {
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["alerts", companyId] });
      }
    },
  });
  const recalc = useMutation({
    mutationFn: () => {
      const target = alertsRecalcTarget(companyId);
      if (!target.allowed) {
        throw new Error("Выберите фирму");
      }
      return recalculateAlerts(target.companyId);
    },
    onSuccess: async () => {
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["alerts", companyId] });
      }
    },
  });
  const writeLocked = recalc.isPending || ack.isPending;
  const openCount =
    alertPayload?.alerts.filter((item) => item.status !== "resolved").length ?? 0;
  const completeness = completenessCaption(alertPayload?.completeness);

  return (
    <Shell>
      <h1 className="mb-4 text-xl font-semibold">Алерты</h1>
      <CompanyWritePicker
        listPhase={selection.listPhase}
        list={selection.list}
        value={selection.selectValue}
        needsPlaceholder={selection.needsPlaceholder}
        disabled={selection.pickerDisabled || writeLocked}
        onSelect={selection.onSelect}
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <p className="text-sm text-slate-600">
          {savedCalculationCaption(alertPayload?.report_date ?? null)}
        </p>
        {completeness ? <p className="text-sm text-slate-600">{completeness}</p> : null}
        <button
          type="button"
          className="rounded border px-3 py-1 disabled:opacity-50"
          disabled={!selection.canWrite || recalc.isPending}
          onClick={() => {
            if (alertsRecalcTarget(companyId).allowed) {
              recalc.mutate();
            }
          }}
        >
          Пересчитать
        </button>
      </div>
      {recalc.isError ? <p className="mb-3 text-red-700">Не удалось пересчитать сигналы.</p> : null}
      {companyId && alerts.isLoading ? <p>Загрузка</p> : null}
      {companyId && alerts.isError ? <p className="text-red-700">Не удалось загрузить сигналы.</p> : null}
      {alertPayload ? (
        <p className="mb-3 text-sm">{alertEmpty(alertPayload.status, openCount)}</p>
      ) : null}
      <ul className="space-y-3">
        {alertPayload?.alerts
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
                  className="mt-2 rounded border px-3 py-1 disabled:opacity-50"
                  disabled={!selection.canWrite || ack.isPending}
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
