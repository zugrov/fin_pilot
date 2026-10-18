import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

import {
  createPlanEvent,
  createPlanPaymentMatch,
  listCompanies,
  loadCalendar,
  loadTransactions,
  moveExpected,
  WalletRequestError,
} from "../api";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import {
  calendarMutationTarget,
  companyScopedData,
  useWritableCompanySelection,
} from "../lib/companySelection";
import {
  applyAfterFailure,
  guardCompanySwitch,
  lockedCompanyFromAttempts,
  resolveSubmit,
  shouldBlockFieldEdit,
  type IdempotentAttempt,
  type PlanCreatePayload,
  type PlanMatchPayload,
} from "../lib/salesPlanForm";

function newKey() {
  return crypto.randomUUID();
}

function failureMeta(exc: unknown): { status: number; code: string; message: string } {
  if (exc instanceof WalletRequestError) {
    return { status: exc.status, code: exc.code, message: exc.message };
  }
  return { status: 0, code: "", message: exc instanceof Error ? exc.message : "Ошибка" };
}

export function CalendarPage() {
  const [amount, setAmount] = useState("150000.00");
  const [dueDate, setDueDate] = useState("2026-10-15");
  const [expectedDate, setExpectedDate] = useState("2026-10-15");
  const [moveTo, setMoveTo] = useState("2026-10-20");
  const [error, setError] = useState("");
  const [createAttempt, setCreateAttempt] = useState<IdempotentAttempt<PlanCreatePayload> | null>(
    null,
  );
  const [matchAttempt, setMatchAttempt] = useState<IdempotentAttempt<PlanMatchPayload> | null>(
    null,
  );
  const [matchEventId, setMatchEventId] = useState("");
  const [matchCashId, setMatchCashId] = useState("");
  const [matchAmount, setMatchAmount] = useState("");

  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const onCompanyChanged = useCallback(() => {
    setError("");
  }, []);
  const selection = useWritableCompanySelection(companies, { onCompanyChanged });
  const { companyId } = selection;
  const lockedCompany = lockedCompanyFromAttempts([createAttempt, matchAttempt]);
  const createLocked = shouldBlockFieldEdit(createAttempt);
  const matchLocked = shouldBlockFieldEdit(matchAttempt);

  const calendar = useQuery({
    queryKey: ["calendar", companyId],
    queryFn: () => loadCalendar(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const transactions = useQuery({
    queryKey: ["transactions", companyId, "posted"],
    queryFn: () => loadTransactions(companyId ?? "", "posted"),
    enabled: Boolean(companyId),
  });
  const events = companyScopedData(companyId, companyId ?? undefined, calendar.data?.events);

  const save = useMutation({
    mutationFn: (attempt: IdempotentAttempt<PlanCreatePayload>) => {
      const p = attempt.payload;
      return createPlanEvent(
        p.companyId,
        {
          direction: p.direction,
          amount: p.amount,
          due_date: p.dueDate,
          expected_date: p.expectedDate,
        },
        attempt.key,
      );
    },
    onSuccess: async () => {
      setError("");
      setCreateAttempt(null);
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["calendar", companyId] });
      }
    },
    onError: (exc, attempt) => {
      const meta = failureMeta(exc);
      setCreateAttempt((current) => {
        if (!current || current.key !== attempt.key) {
          return current;
        }
        return applyAfterFailure(current, meta.status, meta.code);
      });
      setError(meta.message);
    },
  });

  const matchSave = useMutation({
    mutationFn: (attempt: IdempotentAttempt<PlanMatchPayload>) => {
      const p = attempt.payload;
      return createPlanPaymentMatch(
        p.companyId,
        p.eventId,
        p.cashTransactionId,
        p.amount,
        attempt.key,
      );
    },
    onSuccess: async () => {
      setError("");
      setMatchAttempt(null);
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["calendar", companyId] });
        await client.invalidateQueries({ queryKey: ["transactions", companyId] });
      }
    },
    onError: (exc, attempt) => {
      const meta = failureMeta(exc);
      setMatchAttempt((current) => {
        if (!current || current.key !== attempt.key) {
          return current;
        }
        return applyAfterFailure(current, meta.status, meta.code);
      });
      setError(meta.message);
    },
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

  const selectedEvent = events?.find((event) => event.id === matchEventId);
  const cashOptions = useMemo(() => {
    const rows = transactions.data?.transactions ?? [];
    if (!selectedEvent) {
      return [];
    }
    return rows.filter(
      (row) =>
        row.status === "posted" &&
        row.currency === "RUB" &&
        row.direction === selectedEvent.direction,
    );
  }, [selectedEvent, transactions.data?.transactions]);

  function submitCreate() {
    setError("");
    const target = calendarMutationTarget(companyId);
    if (!target.allowed) {
      return;
    }
    const payload: PlanCreatePayload = {
      companyId: target.companyId,
      direction: "out",
      amount,
      dueDate,
      expectedDate,
    };
    const resolved = resolveSubmit(createAttempt, payload, newKey);
    if (resolved.kind === "blocked") {
      setError("Нельзя менять параметры, пока не подтверждён результат отправки.");
      return;
    }
    setCreateAttempt(resolved.attempt);
    save.mutate(resolved.attempt);
  }

  function submitMatch() {
    setError("");
    const target = calendarMutationTarget(companyId);
    if (!target.allowed) {
      return;
    }
    const payload: PlanMatchPayload = {
      companyId: target.companyId,
      eventId: matchEventId,
      cashTransactionId: matchCashId,
      amount: matchAmount,
    };
    const resolved = resolveSubmit(matchAttempt, payload, newKey);
    if (resolved.kind === "blocked") {
      setError("Нельзя менять сопоставление до завершения предыдущей отправки.");
      return;
    }
    setMatchAttempt(resolved.attempt);
    matchSave.mutate(resolved.attempt);
  }

  function onSelectCompany(nextId: string) {
    const guard = guardCompanySwitch(nextId, lockedCompany);
    if (!guard.allowed) {
      setError(guard.message);
      return;
    }
    selection.onSelect(nextId);
  }

  const anyWritePending = save.isPending || shift.isPending || matchSave.isPending;

  return (
    <Shell>
      <h1 className="mb-2 text-xl font-semibold">Календарь</h1>
      <p className="mb-4 text-sm text-slate-600">Это план платежей, не движение денег.</p>
      <CompanyWritePicker
        listPhase={selection.listPhase}
        list={selection.list}
        value={selection.selectValue}
        needsPlaceholder={selection.needsPlaceholder}
        disabled={selection.pickerDisabled || anyWritePending || Boolean(lockedCompany)}
        onSelect={onSelectCompany}
      />
      {companyId && calendar.isLoading ? <p>Загрузка</p> : null}
      {companyId && calendar.isError ? <p className="text-red-700">Не удалось загрузить календарь.</p> : null}
      {events?.length === 0 ? <p className="mb-4">Плановых событий нет.</p> : null}
      <ul className="mb-6 space-y-2">
        {events?.map((event) => (
          <li key={event.id} className="rounded-xl border bg-white p-4 text-sm">
            <p>
              {event.expected_date}: остаток {event.remaining}, оплачено {event.matched ?? "0.00"}, срок{" "}
              {event.due_date}
              {event.overdue ? ", просрочено" : ""}
            </p>
            {event.match_links?.length ? (
              <ul className="mt-2 list-disc pl-5">
                {event.match_links.map((link) => (
                  <li key={`${link.cash_transaction_id}-${link.amount}`}>
                    {link.label}: {link.amount}
                  </li>
                ))}
              </ul>
            ) : null}
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
        className="mb-8 max-w-md space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          submitCreate();
        }}
      >
        <label className="block text-sm">
          Сумма
          <input
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={amount}
            disabled={createLocked || save.isPending}
            onChange={(event) => setAmount(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          Срок (due_date)
          <input
            type="date"
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={dueDate}
            disabled={createLocked || save.isPending}
            onChange={(event) => setDueDate(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          Ожидаемая дата
          <input
            type="date"
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={expectedDate}
            disabled={createLocked || save.isPending}
            onChange={(event) => setExpectedDate(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          Новая ожидаемая дата (перенос выбранного события)
          <input
            type="date"
            className="mt-1 w-full rounded border px-3 py-2"
            value={moveTo}
            onChange={(event) => setMoveTo(event.target.value)}
          />
        </label>
        <button
          className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50"
          type="submit"
          disabled={!selection.canWrite || save.isPending}
        >
          {createAttempt?.phase === "unknown" ? "Повторить отправку" : "Добавить платёж"}
        </button>
      </form>

      <section className="max-w-md space-y-3 border-t pt-4">
        <h2 className="text-lg font-semibold">Сопоставление с операцией</h2>
        <label className="block text-sm">
          Плановое событие
          <select
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={matchEventId}
            disabled={matchLocked || matchSave.isPending}
            onChange={(event) => {
              setMatchEventId(event.target.value);
              setMatchCashId("");
            }}
          >
            <option value="">Выберите</option>
            {events
              ?.filter((event) => event.status !== "cancelled")
              .map((event) => (
                <option key={event.id} value={event.id}>
                  {event.expected_date} · {event.direction} · остаток {event.remaining}
                </option>
              ))}
          </select>
        </label>
        <label className="block text-sm">
          Операция (posted, та же direction и RUB)
          <select
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={matchCashId}
            disabled={matchLocked || matchSave.isPending || !matchEventId}
            onChange={(event) => setMatchCashId(event.target.value)}
          >
            <option value="">Выберите</option>
            {cashOptions.map((row) => (
              <option key={row.id} value={row.id}>
                {row.business_date} · доступно {row.plan_unallocated ?? row.amount} — {row.description}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          Сумма связи
          <input
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={matchAmount}
            disabled={matchLocked || matchSave.isPending}
            onChange={(event) => setMatchAmount(event.target.value)}
          />
        </label>
        <button
          type="button"
          className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50"
          disabled={!selection.canWrite || matchSave.isPending || !matchEventId || !matchCashId}
          onClick={submitMatch}
        >
          {matchAttempt?.phase === "unknown" ? "Повторить сопоставление" : "Сопоставить"}
        </button>
      </section>
      {error ? <p className="mt-4 text-sm text-red-700">{error}</p> : null}
    </Shell>
  );
}
