import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

import {
  createPlanEvent,
  createPlanPaymentMatch,
  listCompanies,
  loadCalendar,
  loadTransactions,
  moveExpected,
  type PlanEvent,
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
  directionLabel,
  EMPTY_PLAN_DRAFT,
  validateExpectedDateOnly,
  validateMatchAmount,
  validatePlanCreate,
} from "../lib/calendarForm";
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

type MoveTarget = Pick<
  PlanEvent,
  "id" | "version" | "amount" | "due_date" | "expected_date" | "remaining"
>;

export function CalendarPage() {
  const [amount, setAmount] = useState<string>(EMPTY_PLAN_DRAFT.amount);
  const [dueDate, setDueDate] = useState<string>(EMPTY_PLAN_DRAFT.dueDate);
  const [expectedDate, setExpectedDate] = useState<string>(EMPTY_PLAN_DRAFT.expectedDate);
  const [moveTarget, setMoveTarget] = useState<MoveTarget | null>(null);
  const [moveNewExpected, setMoveNewExpected] = useState("");
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

  const clearLocalDrafts = useCallback(() => {
    setError("");
    setAmount(EMPTY_PLAN_DRAFT.amount);
    setDueDate(EMPTY_PLAN_DRAFT.dueDate);
    setExpectedDate(EMPTY_PLAN_DRAFT.expectedDate);
    setMoveTarget(null);
    setMoveNewExpected("");
    setMatchEventId("");
    setMatchCashId("");
    setMatchAmount("");
  }, []);

  const onCompanyChanged = useCallback(() => {
    clearLocalDrafts();
  }, [clearLocalDrafts]);

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
      setAmount(EMPTY_PLAN_DRAFT.amount);
      setDueDate(EMPTY_PLAN_DRAFT.dueDate);
      setExpectedDate(EMPTY_PLAN_DRAFT.expectedDate);
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
      setMatchCashId("");
      setMatchAmount("");
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
    mutationFn: (input: { id: string; version: number; expectedDate: string }) =>
      moveExpected(input.id, input.version, input.expectedDate),
    onSuccess: async () => {
      setError("");
      setMoveTarget(null);
      setMoveNewExpected("");
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
    const dir = selectedEvent.direction === "in" ? "in" : "out";
    return rows.filter(
      (row) => row.status === "posted" && row.currency === "RUB" && row.direction === dir,
    );
  }, [selectedEvent, transactions.data?.transactions]);

  function submitCreate() {
    setError("");
    const target = calendarMutationTarget(companyId);
    if (!target.allowed) {
      return;
    }
    const validated = validatePlanCreate({ amount, dueDate, expectedDate });
    if (!validated.ok) {
      setError(validated.message);
      return;
    }
    const payload: PlanCreatePayload = {
      companyId: target.companyId,
      direction: "out",
      amount: validated.amount,
      dueDate: validated.dueDate,
      expectedDate: validated.expectedDate,
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
    if (!matchEventId || !selectedEvent) {
      setError("Выберите плановую выплату.");
      return;
    }
    if (selectedEvent.company_id && selectedEvent.company_id !== target.companyId) {
      setError("Выбранная выплата относится к другой фирме.");
      return;
    }
    const amountCheck = validateMatchAmount(matchAmount);
    if (!amountCheck.ok) {
      setError(amountCheck.message);
      return;
    }
    if (!matchCashId) {
      setError("Выберите фактическую операцию.");
      return;
    }
    const payload: PlanMatchPayload = {
      companyId: target.companyId,
      eventId: matchEventId,
      cashTransactionId: matchCashId,
      amount: amountCheck.value,
    };
    const resolved = resolveSubmit(matchAttempt, payload, newKey);
    if (resolved.kind === "blocked") {
      setError("Нельзя менять сопоставление до завершения предыдущей отправки.");
      return;
    }
    setMatchAttempt(resolved.attempt);
    matchSave.mutate(resolved.attempt);
  }

  function openMoveDialog(event: PlanEvent) {
    if (!companyId || event.company_id && event.company_id !== companyId) {
      setError("Нельзя перенести выплату другой фирмы.");
      return;
    }
    setError("");
    setMoveTarget({
      id: event.id,
      version: event.version,
      amount: event.amount,
      due_date: event.due_date,
      expected_date: event.expected_date,
      remaining: event.remaining,
    });
    setMoveNewExpected(event.expected_date);
  }

  function submitMove() {
    if (!moveTarget) {
      return;
    }
    if (!companyId) {
      return;
    }
    const validated = validateExpectedDateOnly(moveNewExpected);
    if (!validated.ok) {
      setError(validated.message);
      return;
    }
    shift.mutate({
      id: moveTarget.id,
      version: moveTarget.version,
      expectedDate: validated.value,
    });
  }

  function onSelectCompany(nextId: string) {
    const guard = guardCompanySwitch(nextId, lockedCompany);
    if (!guard.allowed) {
      setError(guard.message);
      return;
    }
    clearLocalDrafts();
    selection.onSelect(nextId);
  }

  const anyWritePending = save.isPending || shift.isPending || matchSave.isPending;

  return (
    <Shell title="Календарь">
      <p className="mb-4 text-sm text-ink-muted">
        Здесь плановые выплаты и поступления: это не фактическое движение денег и не банковский платёж.
      </p>
      <CompanyWritePicker
        listPhase={selection.listPhase}
        list={selection.list}
        value={selection.selectValue}
        needsPlaceholder={selection.needsPlaceholder}
        disabled={selection.pickerDisabled || anyWritePending || Boolean(lockedCompany)}
        onSelect={onSelectCompany}
      />
      {companyId && calendar.isLoading ? <p>Загрузка календаря…</p> : null}
      {companyId && calendar.isError ? (
        <p className="text-danger">Не удалось загрузить календарь.</p>
      ) : null}
      {events?.length === 0 ? <p className="mb-4">Плановых событий пока нет.</p> : null}
      <ul className="mb-6 space-y-2">
        {events?.map((event) => (
          <li key={event.id} className="rounded-card border bg-white p-4 text-sm">
            <p>
              {directionLabel(event.direction === "in" ? "in" : "out")}: ожидание {event.expected_date},
              остаток {event.remaining}, срок {event.due_date}
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
              className="mt-2 rounded-control border px-3 py-1 disabled:opacity-50"
              disabled={!selection.canWrite || shift.isPending}
              onClick={() => openMoveDialog(event)}
            >
              Перенести ожидание
            </button>
          </li>
        ))}
      </ul>

      <form
        className="mb-8 max-w-md space-y-3 rounded-card border bg-white p-4"
        onSubmit={(event) => {
          event.preventDefault();
          submitCreate();
        }}
      >
        <h2 className="text-lg font-semibold">Новая плановая выплата</h2>
        <p className="text-sm text-ink-muted">
          Срок — когда платёж должен быть исполнен по договору. Ожидаемая дата — когда вы планируете
          увидеть деньги на счёте (может отличаться от срока).
        </p>
        <label className="block text-sm">
          Сумма, ₽
          <input
            className="mt-1 w-full rounded-control border px-3 py-2 disabled:opacity-50"
            value={amount}
            disabled={createLocked || save.isPending}
            onChange={(event) => setAmount(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          Срок оплаты
          <input
            type="date"
            className="mt-1 w-full rounded-control border px-3 py-2 disabled:opacity-50"
            value={dueDate}
            disabled={createLocked || save.isPending}
            onChange={(event) => setDueDate(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          Ожидаемая дата оплаты
          <input
            type="date"
            className="mt-1 w-full rounded-control border px-3 py-2 disabled:opacity-50"
            value={expectedDate}
            disabled={createLocked || save.isPending}
            onChange={(event) => setExpectedDate(event.target.value)}
          />
        </label>
        <button
          className="rounded-control bg-brand px-4 py-2 text-white disabled:opacity-50"
          type="submit"
          disabled={!selection.canWrite || save.isPending}
        >
          {createAttempt?.phase === "unknown" ? "Повторить отправку" : "Добавить в план"}
        </button>
      </form>

      <section className="max-w-md space-y-3 border-t pt-4">
        <h2 className="text-lg font-semibold">Связать с фактической оплатой</h2>
        <p className="text-sm text-ink-muted">
          Можно выбрать только проведённые операции в рублях с тем же направлением (поступление или
          списание), что и у плановой выплаты.
        </p>
        <label className="block text-sm">
          Плановая выплата
          <select
            className="mt-1 w-full rounded-control border px-3 py-2 disabled:opacity-50"
            value={matchEventId}
            disabled={matchLocked || matchSave.isPending}
            onChange={(event) => {
              setMatchEventId(event.target.value);
              setMatchCashId("");
            }}
          >
            <option value="">Выберите выплату</option>
            {events
              ?.filter((event) => event.status !== "cancelled")
              .map((event) => (
                <option key={event.id} value={event.id}>
                  {event.expected_date} · {directionLabel(event.direction === "in" ? "in" : "out")} ·
                  остаток {event.remaining}
                </option>
              ))}
          </select>
        </label>
        <label className="block text-sm">
          Фактическая операция
          <select
            className="mt-1 w-full rounded-control border px-3 py-2 disabled:opacity-50"
            value={matchCashId}
            disabled={matchLocked || matchSave.isPending || !matchEventId}
            onChange={(event) => setMatchCashId(event.target.value)}
          >
            <option value="">Выберите операцию</option>
            {cashOptions.map((row) => (
              <option key={row.id} value={row.id}>
                {row.business_date} · доступно {row.plan_unallocated ?? row.amount} — {row.description}
              </option>
            ))}
          </select>
        </label>
        {matchEventId && transactions.isLoading ? (
          <p className="text-sm text-ink-muted">Загружаем проведённые операции…</p>
        ) : null}
        {matchEventId && transactions.isError ? (
          <p className="text-sm text-danger">Не удалось загрузить операции для сопоставления.</p>
        ) : null}
        {matchEventId &&
        !transactions.isLoading &&
        !transactions.isError &&
        cashOptions.length === 0 ? (
          <p className="text-sm text-ink-muted">
            Нет подходящих проведённых операций в рублях с нужным направлением.
          </p>
        ) : null}
        <label className="block text-sm">
          Сумма связи, ₽
          <input
            className="mt-1 w-full rounded-control border px-3 py-2 disabled:opacity-50"
            value={matchAmount}
            disabled={matchLocked || matchSave.isPending}
            onChange={(event) => setMatchAmount(event.target.value)}
          />
        </label>
        <button
          type="button"
          className="rounded-control bg-brand px-4 py-2 text-white disabled:opacity-50"
          disabled={!selection.canWrite || matchSave.isPending || !matchEventId || !matchCashId}
          onClick={submitMatch}
        >
          {matchAttempt?.phase === "unknown" ? "Повторить сопоставление" : "Связать с операцией"}
        </button>
      </section>

      {moveTarget ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="move-dialog-title"
        >
          <div className="w-full max-w-md space-y-3 rounded-card bg-white p-4 shadow-lg">
            <h2 id="move-dialog-title" className="text-lg font-semibold">
              Перенос ожидания
            </h2>
            <p className="text-sm text-ink-muted">
              Сумма {moveTarget.amount}, срок {moveTarget.due_date}, текущая ожидаемая дата{" "}
              {moveTarget.expected_date}. Срок оплаты не изменится.
            </p>
            <label className="block text-sm">
              Новая ожидаемая дата оплаты
              <input
                type="date"
                className="mt-1 w-full rounded-control border px-3 py-2"
                value={moveNewExpected}
                disabled={shift.isPending}
                onChange={(event) => setMoveNewExpected(event.target.value)}
              />
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                className="rounded-control bg-brand px-4 py-2 text-white disabled:opacity-50"
                disabled={shift.isPending}
                onClick={submitMove}
              >
                Сохранить перенос
              </button>
              <button
                type="button"
                className="rounded-control border px-4 py-2 disabled:opacity-50"
                disabled={shift.isPending}
                onClick={() => {
                  setMoveTarget(null);
                  setMoveNewExpected("");
                }}
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {error ? <p className="mt-4 text-sm text-danger">{error}</p> : null}
    </Shell>
  );
}
