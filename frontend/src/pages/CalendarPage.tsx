import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { createPlanEvent, listCompanies, loadCalendar, moveExpected } from "../api";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import {
  calendarMutationTarget,
  companyScopedData,
  useWritableCompanySelection,
} from "../lib/companySelection";

export function CalendarPage() {
  const [amount, setAmount] = useState("150000.00");
  const [day, setDay] = useState("2026-10-15");
  const [moveTo, setMoveTo] = useState("2026-10-20");
  const [error, setError] = useState("");
  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const onCompanyChanged = useCallback(() => {
    setError("");
  }, []);
  const selection = useWritableCompanySelection(companies, {
    onCompanyChanged,
  });
  const { companyId } = selection;
  const calendar = useQuery({
    queryKey: ["calendar", companyId],
    queryFn: () => loadCalendar(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const events = companyScopedData(companyId, companyId ?? undefined, calendar.data?.events);
  const save = useMutation({
    mutationFn: () => {
      const target = calendarMutationTarget(companyId);
      if (!target.allowed) {
        throw new Error("Выберите фирму");
      }
      return createPlanEvent(target.companyId, amount, day);
    },
    onSuccess: async () => {
      setError("");
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["calendar", companyId] });
      }
    },
    onError: (exc: Error) => setError(exc.message),
  });
  const shift = useMutation({
    mutationFn: (event: { id: string; version: number }) => moveExpected(event.id, event.version, moveTo),
    onSuccess: async () => {
      setError("");
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["calendar", companyId] });
      }
    },
    onError: (exc: Error) => setError(exc.message),
  });
  const anyWritePending = save.isPending || shift.isPending;

  return (
    <Shell>
      <h1 className="mb-2 text-xl font-semibold">Календарь</h1>
      <p className="mb-4 text-sm text-slate-600">Это план платежей, не движение денег.</p>
      <CompanyWritePicker
        listPhase={selection.listPhase}
        list={selection.list}
        value={selection.selectValue}
        needsPlaceholder={selection.needsPlaceholder}
        disabled={selection.pickerDisabled || anyWritePending}
        onSelect={selection.onSelect}
      />
      {companyId && calendar.isLoading ? <p>Загрузка</p> : null}
      {companyId && calendar.isError ? <p className="text-red-700">Не удалось загрузить календарь.</p> : null}
      {events?.length === 0 ? <p className="mb-4">Плановых событий нет.</p> : null}
      <ul className="mb-6 space-y-2">
        {events?.map((event) => (
          <li key={event.id} className="rounded-xl border bg-white p-4 text-sm">
            <p>
              {event.expected_date}: остаток {event.remaining}, срок {event.due_date}
              {event.overdue ? ", просрочено" : ""}
            </p>
            <button
              type="button"
              className="mt-2 rounded border px-3 py-1 disabled:opacity-50"
              disabled={!selection.canWrite || shift.isPending}
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
          if (!calendarMutationTarget(companyId).allowed) {
            return;
          }
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
        <button
          className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50"
          type="submit"
          disabled={!selection.canWrite || save.isPending}
        >
          Добавить платёж
        </button>
      </form>
    </Shell>
  );
}
