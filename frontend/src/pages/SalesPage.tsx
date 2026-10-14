import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { createRevenue, listCompanies, loadRevenue } from "../api";
import { Shell } from "../components/Shell";

export function SalesPage() {
  const [inc, setInc] = useState("120000.00");
  const [ex, setEx] = useState("100000.00");
  const [vat, setVat] = useState("20000.00");
  const [error, setError] = useState("");
  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const companyId = companies.data?.companies[0]?.id;
  const sales = useQuery({
    queryKey: ["sales", companyId],
    queryFn: () => loadRevenue(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const save = useMutation({
    mutationFn: () => createRevenue(companyId ?? "", inc, ex, vat),
    onSuccess: async () => {
      setError("");
      await client.invalidateQueries({ queryKey: ["sales", companyId] });
    },
    onError: (exc: Error) => setError(exc.message),
  });

  return (
    <Shell>
      <h1 className="mb-2 text-xl font-semibold">Продажи</h1>
      <p className="mb-4 text-sm text-slate-600">Это не таблица поступлений.</p>
      {sales.isLoading ? <p>Загрузка</p> : null}
      {sales.isError ? <p className="text-red-700">Не удалось загрузить продажи.</p> : null}
      {sales.data?.entries.length === 0 ? <p className="mb-4">Продаж нет.</p> : null}
      <ul className="mb-6 space-y-2">
        {sales.data?.entries.map((entry) => (
          <li key={entry.id} className="rounded-xl border bg-white p-4">
            {entry.recognition_date}: {entry.amount_ex_vat ?? entry.amount_inc_vat} без НДС,{" "}
            {entry.entry_type === "return" ? "возврат" : "продажа"}
          </li>
        ))}
      </ul>
      <form
        className="max-w-md space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <label className="block text-sm">
          Сумма с НДС
          <input className="mt-1 w-full rounded border px-3 py-2" value={inc} onChange={(event) => setInc(event.target.value)} />
        </label>
        <label className="block text-sm">
          Без НДС
          <input className="mt-1 w-full rounded border px-3 py-2" value={ex} onChange={(event) => setEx(event.target.value)} />
        </label>
        <label className="block text-sm">
          НДС
          <input className="mt-1 w-full rounded border px-3 py-2" value={vat} onChange={(event) => setVat(event.target.value)} />
        </label>
        {error ? <p className="text-sm text-red-700">{error}</p> : null}
        <button className="rounded bg-slate-900 px-4 py-2 text-white" type="submit" disabled={!companyId || save.isPending}>
          Добавить продажу
        </button>
      </form>
    </Shell>
  );
}
