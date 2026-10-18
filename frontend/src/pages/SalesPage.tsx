import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createRevenue,
  createRevenueCashMatch,
  listCompanies,
  loadRevenue,
  loadTransactions,
  WalletRequestError,
} from "../api";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import { companyDate } from "../lib/forecast";
import {
  companyScopedData,
  salesMutationTarget,
  useWritableCompanySelection,
} from "../lib/companySelection";
import {
  applyAfterFailure,
  guardCompanySwitch,
  lockedCompanyFromAttempts,
  resolveSubmit,
  shouldBlockFieldEdit,
  type IdempotentAttempt,
  type RevenueCreatePayload,
  type RevenueMatchPayload,
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

export function SalesPage() {
  const [inc, setInc] = useState("120000.00");
  const [ex, setEx] = useState("100000.00");
  const [vat, setVat] = useState("20000.00");
  const [recognitionDate, setRecognitionDate] = useState("");
  const [documentNumber, setDocumentNumber] = useState("");
  const [externalId, setExternalId] = useState("");
  const [error, setError] = useState("");
  const [createAttempt, setCreateAttempt] = useState<IdempotentAttempt<RevenueCreatePayload> | null>(
    null,
  );
  const [matchAttempt, setMatchAttempt] = useState<IdempotentAttempt<RevenueMatchPayload> | null>(
    null,
  );
  const [matchEntryId, setMatchEntryId] = useState("");
  const [matchCashId, setMatchCashId] = useState("");
  const [matchAmount, setMatchAmount] = useState("");

  const client = useQueryClient();
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const onCompanyChanged = useCallback(() => {
    setError("");
  }, []);
  const selection = useWritableCompanySelection(companies, { onCompanyChanged });
  const { companyId, company } = selection;

  useEffect(() => {
    if (!company?.timezone || recognitionDate) {
      return;
    }
    setRecognitionDate(companyDate(company.timezone));
  }, [company?.timezone, recognitionDate]);

  const lockedCompany = lockedCompanyFromAttempts([createAttempt, matchAttempt]);
  const createLocked = shouldBlockFieldEdit(createAttempt);
  const matchLocked = shouldBlockFieldEdit(matchAttempt);

  const sales = useQuery({
    queryKey: ["sales", companyId],
    queryFn: () => loadRevenue(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const transactions = useQuery({
    queryKey: ["transactions", companyId, "posted"],
    queryFn: () => loadTransactions(companyId ?? "", "posted"),
    enabled: Boolean(companyId),
  });
  const entries = companyScopedData(companyId, companyId ?? undefined, sales.data?.entries);
  const inflows = useMemo(
    () =>
      (transactions.data?.transactions ?? []).filter(
        (row) => row.direction === "in" && row.currency === "RUB" && row.status === "posted",
      ),
    [transactions.data?.transactions],
  );

  const save = useMutation({
    mutationFn: (attempt: IdempotentAttempt<RevenueCreatePayload>) => {
      const p = attempt.payload;
      return createRevenue(
        p.companyId,
        {
          recognition_date: p.recognitionDate,
          amount_inc_vat: p.amountInc,
          amount_ex_vat: p.amountEx,
          vat_amount: p.vat,
          document_number: p.documentNumber || undefined,
          external_id: p.externalId || undefined,
        },
        attempt.key,
      );
    },
    onSuccess: async () => {
      setError("");
      setCreateAttempt(null);
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["sales", companyId] });
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
      const suffix =
        applyAfterFailure({ ...attempt, phase: "executing" }, meta.status, meta.code) === null
          ? ""
          : " Ответ сервера не получен. Параметры зафиксированы — повторите отправку с тем же ключом.";
      setError(`${meta.message}${suffix}`);
    },
  });

  const matchSave = useMutation({
    mutationFn: (attempt: IdempotentAttempt<RevenueMatchPayload>) => {
      const p = attempt.payload;
      return createRevenueCashMatch(
        p.companyId,
        p.revenueEntryId,
        p.cashTransactionId,
        p.amount,
        attempt.key,
      );
    },
    onSuccess: async () => {
      setError("");
      setMatchAttempt(null);
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["sales", companyId] });
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

  function submitCreate() {
    setError("");
    const target = salesMutationTarget(companyId);
    if (!target.allowed || !recognitionDate) {
      setError(company?.timezone ? "Заполните дату признания" : "Укажите дату признания вручную");
      return;
    }
    const payload: RevenueCreatePayload = {
      companyId: target.companyId,
      recognitionDate,
      amountInc: inc,
      amountEx: ex,
      vat,
      documentNumber: documentNumber.trim(),
      externalId: externalId.trim(),
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
    const target = salesMutationTarget(companyId);
    if (!target.allowed) {
      return;
    }
    const payload: RevenueMatchPayload = {
      companyId: target.companyId,
      revenueEntryId: matchEntryId,
      cashTransactionId: matchCashId,
      amount: matchAmount,
    };
    const resolved = resolveSubmit(matchAttempt, payload, newKey);
    if (resolved.kind === "blocked") {
      setError("Нельзя менять параметры сопоставления до завершения предыдущей отправки.");
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

  const pickerDisabled =
    selection.pickerDisabled || save.isPending || matchSave.isPending || Boolean(lockedCompany);

  return (
    <Shell>
      <h1 className="mb-2 text-xl font-semibold">Продажи</h1>
      <p className="mb-4 text-sm text-slate-600">Это не таблица поступлений.</p>
      <CompanyWritePicker
        listPhase={selection.listPhase}
        list={selection.list}
        value={selection.selectValue}
        needsPlaceholder={selection.needsPlaceholder}
        disabled={pickerDisabled}
        onSelect={onSelectCompany}
      />
      {company?.timezone ? (
        <p className="mb-3 text-sm text-slate-600">Часовой пояс фирмы: {company.timezone}</p>
      ) : companyId ? (
        <p className="mb-3 text-sm text-amber-800">Часовой пояс фирмы неизвестен — укажите дату вручную.</p>
      ) : null}
      {companyId && sales.isLoading ? <p>Загрузка</p> : null}
      {companyId && sales.isError ? <p className="text-red-700">Не удалось загрузить продажи.</p> : null}
      {entries?.length === 0 ? <p className="mb-4">Продаж нет.</p> : null}
      <ul className="mb-6 space-y-2">
        {entries?.map((entry) => (
          <li key={entry.id} className="rounded-xl border bg-white p-4 text-sm">
            <p>
              {entry.recognition_date}: {entry.amount_ex_vat ?? entry.amount_inc_vat} без НДС,{" "}
              {entry.entry_type === "return" ? "возврат" : "продажа"}
            </p>
            <p>
              Связано {entry.matched_amount ?? "0.00"}, остаток {entry.unallocated_amount ?? "—"}
            </p>
            {entry.match_links?.length ? (
              <ul className="mt-2 list-disc pl-5">
                {entry.match_links.map((link) => (
                  <li key={`${link.cash_transaction_id}-${link.amount}`}>
                    {link.label}: {link.amount}
                  </li>
                ))}
              </ul>
            ) : null}
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
          Дата признания
          <input
            type="date"
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={recognitionDate}
            disabled={createLocked || save.isPending}
            onChange={(event) => setRecognitionDate(event.target.value)}
            required
          />
        </label>
        <label className="block text-sm">
          Номер документа
          <input
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={documentNumber}
            disabled={createLocked || save.isPending}
            onChange={(event) => setDocumentNumber(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          Внешний ID (не ключ идемпотентности)
          <input
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={externalId}
            disabled={createLocked || save.isPending}
            onChange={(event) => setExternalId(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          Сумма с НДС
          <input
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={inc}
            disabled={createLocked || save.isPending}
            onChange={(event) => setInc(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          Без НДС
          <input
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={ex}
            disabled={createLocked || save.isPending}
            onChange={(event) => setEx(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          НДС
          <input
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={vat}
            disabled={createLocked || save.isPending}
            onChange={(event) => setVat(event.target.value)}
          />
        </label>
        <button
          className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50"
          type="submit"
          disabled={!selection.canWrite || save.isPending || !recognitionDate}
        >
          {createAttempt?.phase === "unknown" ? "Повторить отправку" : "Добавить продажу"}
        </button>
      </form>

      <section className="max-w-md space-y-3 border-t pt-4">
        <h2 className="text-lg font-semibold">Сопоставление с поступлением</h2>
        <label className="block text-sm">
          Продажа
          <select
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={matchEntryId}
            disabled={matchLocked || matchSave.isPending}
            onChange={(event) => setMatchEntryId(event.target.value)}
          >
            <option value="">Выберите</option>
            {entries
              ?.filter((e) => e.entry_type === "sale" && e.status === "posted")
              .map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.recognition_date} · остаток {entry.unallocated_amount ?? entry.amount_inc_vat}
                </option>
              ))}
          </select>
        </label>
        <label className="block text-sm">
          Поступление (posted, in, RUB)
          <select
            className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
            value={matchCashId}
            disabled={matchLocked || matchSave.isPending}
            onChange={(event) => setMatchCashId(event.target.value)}
          >
            <option value="">Выберите</option>
            {inflows.map((row) => (
              <option key={row.id} value={row.id}>
                {row.business_date} · доступно {row.revenue_unallocated ?? row.amount} — {row.description}
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
          disabled={!selection.canWrite || matchSave.isPending || !matchEntryId || !matchCashId}
          onClick={submitMatch}
        >
          {matchAttempt?.phase === "unknown" ? "Повторить сопоставление" : "Сопоставить"}
        </button>
      </section>
      {error ? <p className="mt-4 text-sm text-red-700">{error}</p> : null}
    </Shell>
  );
}
