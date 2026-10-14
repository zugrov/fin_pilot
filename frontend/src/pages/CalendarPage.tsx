import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { createPlanEvent, listCompanies, loadCalendar, moveExpected } from "../api";
import { Shell } from "../components/Shell";

export function CalendarPage() {
  const [amount, setAmount] = useState("150000.00");
  const [day, setDay] = useState("2026-10-15");
  const [moveTo, setMoveTo] = useState("2026-10-20");
  const [error, setError] = useState("");
  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const companyId = companies.data?.companies[0]?.id;
  const calendar = useQuery({
    queryKey: ["calendar", companyId],
    queryFn: () => loadCalendar(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const save = useMutation({
    mutationFn: () => createPlanEvent(companyId ?? "", amount, day),
    onSuccess: async () => {
      setError("");
      await client.invalidateQueries({ queryKey: ["calendar", companyId] });
    },
    onError: (exc: Error) => setError(exc.message),
  });
  const shift = useMutation({
    mutationFn: (event: { id: string; version: number }) => moveExpected(event.id, event.version, moveTo),
    onSuccess: async () => {
      setError("");
      await client.invalidateQueries({ queryKey: ["calendar", companyId] });
    },
    onError: (exc: Error) => setError(exc.message),
  });

  return (
    <Shell>
      <h1 className="mb-2 text-xl font-semibold">Календарь</h1>
      <p className="mb-4 text-sm text-slate-600">Это план платежей, не движение денег.</p>
      {calendar.isLoading ? <p>Загрузка</p> : null}
      {calendar.isError ? <p className="text-red-700">Не удалось загрузить календарь.</p> : null}
      {calendar.data?.events.length === 0 ? <p className="mb-4">Плановых событий нет.</p> : null}
      <ul className="mb-6 space-y-2">
        {calendar.data?.events.map((event) => (
          <li key={event.id} className="rounded-xl border bg-white p-4 text-sm">
            <p>
              {event.expected_date}: остаток {event.remaining}, срок {event.due_date}
              {event.overdue ? ", просрочено" : ""}
            </p>
            <button
              type="button"
              className="mt-2 rounded border px-3 py-1"
              onClick={() => shift.mutate(event)}
            >
              Перенести ожидание
            </button>
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
          Сумма
          <input className="mt-1 w-full rounded border px-3 py-2" value={amount} onChange={(event) => setAmount(event.target.value)} />
        </label>
        <label className="block text-sm">
          Дата
          <input className="mt-1 w-full rounded border px-3 py-2" value={day} onChange={(event) => setDay(event.target.value)} />
        </label>
        <label className="block text-sm">
          Новая ожидаемая дата
          <input className="mt-1 w-full rounded border px-3 py-2" value={moveTo} onChange={(event) => setMoveTo(event.target.value)} />
        </label>
        {error ? <p className="text-sm text-red-700">{error}</p> : null}
        <button className="rounded bg-slate-900 px-4 py-2 text-white" type="submit" disabled={!companyId || save.isPending}>
          Добавить платёж
        </button>
      </form>
    </Shell>
  );
}
