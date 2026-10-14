import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { approveBudget, createBudget, listCompanies, loadPlanFact } from "../api";
import { Shell } from "../components/Shell";
import { planFactText } from "../lib/budget";

export function BudgetsPage() {
  const [amount, setAmount] = useState("0.00");
  const [draftId, setDraftId] = useState("");
  const [error, setError] = useState("");
  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const companyId = companies.data?.companies[0]?.id;
  const fact = useQuery({
    queryKey: ["plan-fact", companyId],
    queryFn: () => loadPlanFact(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const save = useMutation({
    mutationFn: () => createBudget(companyId ?? "", amount),
    onSuccess: async (draft) => {
      setError("");
      setDraftId(draft.id);
      await client.invalidateQueries({ queryKey: ["plan-fact", companyId] });
    },
    onError: (exc: Error) => setError(exc.message),
  });
  const approve = useMutation({
    mutationFn: () => approveBudget(draftId),
    onSuccess: async () => {
      setError("");
      setDraftId("");
      await client.invalidateQueries({ queryKey: ["plan-fact", companyId] });
    },
    onError: (exc: Error) => setError(exc.message),
  });

  return (
    <Shell>
      <h1 className="mb-2 text-xl font-semibold">Бюджет</h1>
      <p className="mb-4 text-sm text-slate-600">
        Это план расходов, не движение денег и не прогноз.
      </p>
      {fact.isLoading ? <p>Загрузка</p> : null}
      {fact.isError ? <p className="text-red-700">Не удалось посчитать план-факт.</p> : null}
      {error ? <p className="mb-3 text-red-700">{error}</p> : null}
      {fact.data?.bases.map((basis) => (
        <section key={basis.basis} className="mb-4 rounded-xl border bg-white p-4">
          <p className="text-sm text-slate-600">{basis.basis}</p>
          {basis.status === "unavailable" ? (
            <p>Нет утверждённого бюджета</p>
          ) : null}
          <ul className="mt-2 space-y-2">
            {basis.lines.map((line) => (
              <li key={`${line.metric_type}-${line.plan_to_date}`}>
                {line.metric_type}: план {line.plan_to_date ?? "—"}, факт {line.fact ?? "—"},{" "}
                {planFactText(line.status, line.fact, line.percent)}
              </li>
            ))}
          </ul>
        </section>
      ))}
      <label className="mb-3 block text-sm">
        Сумма расхода на октябрь
        <input
          className="mt-1 block rounded border px-3 py-2"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
        />
      </label>
      <div className="flex gap-2">
        <button
          type="button"
          className="rounded border px-3 py-2"
          disabled={!companyId || save.isPending}
          onClick={() => save.mutate()}
        >
          Создать черновик
        </button>
        <button
          type="button"
          className="rounded border px-3 py-2"
          disabled={!draftId || approve.isPending}
          onClick={() => approve.mutate()}
        >
          Утвердить
        </button>
      </div>
    </Shell>
  );
}
