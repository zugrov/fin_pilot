import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  applyClassificationRulePage,
  classifyCashTransaction,
  createClassificationRule,
  listCashCategories,
  listClassificationRules,
  listCompanies,
  loadUnclassifiedSummary,
  loadUnclassifiedTransactions,
  patchClassificationRule,
  previewClassificationRule,
  type CashTransactionRow,
  type ClassificationRuleRow,
  WalletRequestError,
} from "../api";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import type { ApplyCounters } from "../lib/classificationApply";
import {
  cashFlowSectionLabel,
  EMPTY_RULE_DRAFT,
  formatCounterparty,
  formatRuleConditionsHuman,
  ruleEnabledLabel,
  validateRuleCreate,
  type RuleConditionsDraft,
  type RuleCreatePayload,
} from "../lib/classificationForm";
import { directionLabel } from "../lib/calendarForm";
import { companyScopedData, useWritableCompanySelection } from "../lib/companySelection";
import { monthRangeInTimeZone, validatePeriod } from "../lib/periodRange";
import {
  applyAfterFailure,
  guardCompanySwitch,
  lockedCompanyFromAttempts,
  resolveSubmit,
  shouldBlockFieldEdit,
  type IdempotentAttempt,
} from "../lib/salesPlanForm";

function newKey() {
  return crypto.randomUUID();
}

function failureMessage(exc: unknown): string {
  if (exc instanceof WalletRequestError) {
    return exc.message;
  }
  return exc instanceof Error ? exc.message : "Ошибка";
}

function categoryLabel(
  code: string,
  categories: { code: string; name: string; cash_flow_section: string }[],
): string {
  const found = categories.find((item) => item.code === code);
  if (!found) {
    return code;
  }
  return `${found.name} (${cashFlowSectionLabel(found.cash_flow_section)})`;
}

export function ClassificationPage() {
  const client = useQueryClient();
  const [error, setError] = useState("");
  const [ruleDraft, setRuleDraft] = useState(EMPTY_RULE_DRAFT);
  const [createAttempt, setCreateAttempt] = useState<IdempotentAttempt<RuleCreatePayload> | null>(
    null,
  );
  const [previewRuleId, setPreviewRuleId] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<string>("");
  const [applyDialog, setApplyDialog] = useState<ClassificationRuleRow | null>(null);
  const [applyPreview, setApplyPreview] = useState<{
    total_matches: number;
    skipped_locked: number;
    skipped_categorized: number;
    skipped_higher_priority: number;
  } | null>(null);
  const [applyProgress, setApplyProgress] = useState<ApplyCounters | null>(null);
  const [applyRunning, setApplyRunning] = useState(false);
  const [applyPaused, setApplyPaused] = useState(false);
  const [applyError, setApplyError] = useState("");
  const [applyCursor, setApplyCursor] = useState<{
    business_date: string;
    transaction_id: string;
  } | null>(null);
  const [pendingCategory, setPendingCategory] = useState<Record<string, string>>({});
  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");
  const [unclassifiedRows, setUnclassifiedRows] = useState<CashTransactionRow[]>([]);
  const [unclassifiedCursor, setUnclassifiedCursor] = useState<{
    business_date: string;
    transaction_id: string;
  } | null>(null);
  const [unclassifiedHasMore, setUnclassifiedHasMore] = useState(false);

  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });

  const clearLocal = useCallback(() => {
    setError("");
    setRuleDraft(EMPTY_RULE_DRAFT);
    setCreateAttempt(null);
    setPreviewRuleId(null);
    setPreviewResult("");
    setApplyDialog(null);
    setApplyPreview(null);
    setApplyProgress(null);
    setApplyRunning(false);
    setApplyPaused(false);
    setApplyError("");
    setUnclassifiedRows([]);
    setUnclassifiedCursor(null);
    setUnclassifiedHasMore(false);
  }, []);

  const onCompanyChanged = useCallback(() => {
    clearLocal();
    setPeriodFrom("");
    setPeriodTo("");
  }, [clearLocal]);

  const selection = useWritableCompanySelection(companies, {
    onCompanyChanged,
    writePending: applyRunning,
  });
  const { companyId, company } = selection;
  const lockedCompany = lockedCompanyFromAttempts([createAttempt]);
  const createLocked = shouldBlockFieldEdit(createAttempt);

  useEffect(() => {
    if (!company?.timezone || periodFrom) {
      return;
    }
    const range = monthRangeInTimeZone(company.timezone);
    setPeriodFrom(range.from);
    setPeriodTo(range.to);
  }, [company?.timezone, periodFrom]);

  const periodOk = validatePeriod(periodFrom, periodTo).ok;

  const rules = useQuery({
    queryKey: ["classification-rules", companyId],
    queryFn: () => listClassificationRules(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const categories = useQuery({
    queryKey: ["cash-categories", companyId],
    queryFn: () => listCashCategories(companyId ?? ""),
    enabled: Boolean(companyId),
  });
  const summary = useQuery({
    queryKey: ["unclassified-summary", companyId, periodFrom, periodTo],
    queryFn: () => loadUnclassifiedSummary(companyId ?? "", periodFrom, periodTo),
    enabled: Boolean(companyId) && periodOk,
  });

  const loadFirstUnclassified = useCallback(async () => {
    if (!companyId || !periodOk) {
      return;
    }
    const page = await loadUnclassifiedTransactions(companyId, {
      dateFrom: periodFrom,
      dateTo: periodTo,
      limit: 50,
      cursor: null,
    });
    setUnclassifiedRows(page.transactions);
    setUnclassifiedCursor(page.cursor);
    setUnclassifiedHasMore(page.has_more);
  }, [companyId, periodFrom, periodTo, periodOk]);

  useEffect(() => {
    if (!companyId || !periodOk) {
      setUnclassifiedRows([]);
      return;
    }
    void loadFirstUnclassified().catch((exc) => setError(failureMessage(exc)));
  }, [companyId, periodFrom, periodTo, periodOk, loadFirstUnclassified]);

  const ruleList = companyScopedData(companyId, companyId ?? undefined, rules.data?.rules);
  const categoryList = companyScopedData(companyId, companyId ?? undefined, categories.data?.categories);

  const createRule = useMutation({
    mutationFn: (attempt: IdempotentAttempt<RuleCreatePayload>) => {
      const p = attempt.payload;
      return createClassificationRule(p.companyId, {
        name: p.name,
        priority: p.priority,
        conditions: p.conditions,
        category_code: p.categoryCode,
      });
    },
    onSuccess: async () => {
      setCreateAttempt(null);
      setRuleDraft(EMPTY_RULE_DRAFT);
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["classification-rules", companyId] });
      }
    },
    onError: (exc, attempt) => {
      const status = exc instanceof WalletRequestError ? exc.status : 0;
      const code = exc instanceof WalletRequestError ? exc.code : "";
      setCreateAttempt((current) => {
        if (!current || current.key !== attempt.key) {
          return current;
        }
        return applyAfterFailure(current, status, code);
      });
      setError(failureMessage(exc));
    },
  });

  const patchRule = useMutation({
    mutationFn: (input: {
      ruleId: string;
      body: { enabled?: boolean; priority?: number; name?: string };
    }) =>
      patchClassificationRule(input.ruleId, {
        company_id: companyId ?? "",
        ...input.body,
      }),
    onSuccess: async () => {
      if (companyId) {
        await client.invalidateQueries({ queryKey: ["classification-rules", companyId] });
      }
    },
    onError: (exc) => setError(failureMessage(exc)),
  });

  const classifyTx = useMutation({
    mutationFn: (input: { txId: string; version: number; categoryId: string }) =>
      classifyCashTransaction(input.txId, {
        version: input.version,
        category_id: input.categoryId,
      }),
    onSuccess: async () => {
      if (companyId && periodOk) {
        await client.invalidateQueries({ queryKey: ["unclassified-summary", companyId] });
        await loadFirstUnclassified();
      }
    },
    onError: (exc) => setError(failureMessage(exc)),
  });

  async function refreshAfterApply() {
    if (!companyId || !periodOk) {
      return;
    }
    await client.invalidateQueries({ queryKey: ["unclassified-summary", companyId] });
    await loadFirstUnclassified();
    await client.invalidateQueries({ queryKey: ["classification-rules", companyId] });
  }

  async function runApplyLoop(ruleId: string, resumeCursor: typeof applyCursor = null) {
    if (!companyId) {
      return;
    }
    setApplyRunning(true);
    setApplyPaused(false);
    setApplyError("");
    if (!resumeCursor) {
      setApplyProgress(null);
      setApplyCursor(null);
    }
    let cursor = resumeCursor;
    let totals = applyProgress ?? {
      applied: 0,
      skipped_locked: 0,
      skipped_categorized: 0,
      skipped_higher_priority: 0,
      total_matches: 0,
    };
    try {
      for (;;) {
        const page = await applyClassificationRulePage(ruleId, companyId, cursor);
        totals = {
          applied: totals.applied + page.applied,
          skipped_locked: totals.skipped_locked + page.skipped_locked,
          skipped_categorized: totals.skipped_categorized + page.skipped_categorized,
          skipped_higher_priority: totals.skipped_higher_priority + page.skipped_higher_priority,
          total_matches: totals.total_matches + page.total_matches,
        };
        setApplyProgress({ ...totals });
        if (!page.has_more) {
          setApplyDialog(null);
          setApplyPreview(null);
          setApplyCursor(null);
          await refreshAfterApply();
          break;
        }
        if (!page.cursor) {
          throw new Error("Сервер не вернул курсор продолжения");
        }
        cursor = page.cursor;
        setApplyCursor(cursor);
      }
    } catch (exc) {
      setApplyError(failureMessage(exc));
      setApplyPaused(true);
      setApplyCursor(cursor);
    } finally {
      setApplyRunning(false);
    }
  }

  async function openApplyDialog(rule: ClassificationRuleRow) {
    if (!companyId) {
      return;
    }
    setApplyError("");
    const preview = await previewClassificationRule(rule.id, companyId);
    setApplyPreview({
      total_matches: preview.total_matches,
      skipped_locked: preview.skipped_locked,
      skipped_categorized: preview.skipped_categorized,
      skipped_higher_priority: preview.skipped_higher_priority,
    });
    setApplyDialog(rule);
  }

  async function runPreview(ruleId: string) {
    if (!companyId) {
      return;
    }
    setPreviewRuleId(ruleId);
    setPreviewResult("");
    try {
      const body = await previewClassificationRule(ruleId, companyId);
      const lines = body.matches.map(
        (item) => `${item.description || "—"} → ${categoryLabel(item.category_code, categoryList ?? [])}`,
      );
      setPreviewResult(
        `Совпадений: ${body.total_matches}${body.truncated ? " (показаны первые)" : ""}.` +
          (lines.length ? `\n${lines.join("\n")}` : ""),
      );
    } catch (exc) {
      setPreviewResult(failureMessage(exc));
    }
  }

  function submitCreateRule(event: React.FormEvent) {
    event.preventDefault();
    if (!companyId) {
      return;
    }
    const validated = validateRuleCreate(ruleDraft);
    if (!validated.ok) {
      setError(validated.message);
      return;
    }
    const payload: RuleCreatePayload = { companyId, ...validated.payload };
    const resolved = resolveSubmit(createAttempt, payload, newKey);
    if (resolved.kind === "blocked") {
      setError("Дождитесь результата предыдущей отправки или измените данные.");
      return;
    }
    setCreateAttempt(resolved.attempt);
    setError("");
    createRule.mutate(resolved.attempt);
  }

  function onSelectCompany(nextId: string) {
    const guard = guardCompanySwitch(nextId, lockedCompany ?? (applyRunning ? companyId : null));
    if (!guard.allowed) {
      setError(guard.message);
      return;
    }
    clearLocal();
    selection.onSelect(nextId);
  }

  async function loadMoreUnclassified() {
    if (!companyId || !unclassifiedCursor || !periodOk) {
      return;
    }
    const page = await loadUnclassifiedTransactions(companyId, {
      dateFrom: periodFrom,
      dateTo: periodTo,
      limit: 50,
      cursor: unclassifiedCursor,
    });
    setUnclassifiedRows((rows) => [...rows, ...page.transactions]);
    setUnclassifiedCursor(page.cursor);
    setUnclassifiedHasMore(page.has_more);
  }

  const summaryData = companyScopedData(companyId, companyId ?? undefined, summary.data);

  const unclassifiedState = useMemo(() => {
    if (!companyId) {
      return "idle";
    }
    if (!periodOk) {
      return "period";
    }
    if (summary.isLoading) {
      return "loading";
    }
    if (summary.isError) {
      return "error";
    }
    if (summaryData && summaryData.in.count === 0 && summaryData.out.count === 0 && unclassifiedRows.length === 0) {
      return "empty";
    }
    return "ready";
  }, [companyId, periodOk, summary.isLoading, summary.isError, summaryData, unclassifiedRows.length]);

  return (
    <Shell>
      <h1 className="mb-2 text-xl font-semibold">Классификация</h1>
      <p className="mb-4 text-sm text-slate-600">
        Неклассифицированные операции и правила автоматической категории для отчёта о движении денег.
      </p>
      <CompanyWritePicker
        listPhase={selection.listPhase}
        list={selection.list}
        value={selection.selectValue}
        needsPlaceholder={selection.needsPlaceholder}
        disabled={selection.pickerDisabled || applyRunning || Boolean(lockedCompany)}
        onSelect={onSelectCompany}
      />
      {error ? <p className="mb-4 text-sm text-red-700">{error}</p> : null}

      <section className="mb-8 rounded-xl border bg-white p-4" data-testid="unclassified-block">
        <h2 className="mb-3 text-lg font-semibold">Неклассифицированные операции</h2>
        <div className="mb-4 flex flex-wrap gap-3 text-sm">
          <label>
            С
            <input
              type="date"
              className="ml-2 rounded border px-2 py-1"
              value={periodFrom}
              onChange={(event) => setPeriodFrom(event.target.value)}
            />
          </label>
          <label>
            По
            <input
              type="date"
              className="ml-2 rounded border px-2 py-1"
              value={periodTo}
              onChange={(event) => setPeriodTo(event.target.value)}
            />
          </label>
        </div>
        {unclassifiedState === "loading" ? (
          <p className="text-sm text-slate-600" data-testid="unclassified-loading">
            Загрузка сводки…
          </p>
        ) : null}
        {unclassifiedState === "error" ? (
          <p className="text-sm text-red-700" data-testid="unclassified-error">
            Не удалось загрузить сводку.
          </p>
        ) : null}
        {summaryData && unclassifiedState !== "loading" && unclassifiedState !== "error" ? (
          <p className="mb-4 text-sm" data-testid="unclassified-summary">
            Поступления: {summaryData.in.count} на {summaryData.in.amount} ₽; списания:{" "}
            {summaryData.out.count} на {summaryData.out.amount} ₽
          </p>
        ) : null}
        {unclassifiedState === "empty" ? (
          <p className="text-sm text-slate-600" data-testid="unclassified-empty">
            Нет операций без категории за выбранный период.
          </p>
        ) : null}
        {unclassifiedRows.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b">
                  <th className="py-2 pr-2">Дата</th>
                  <th className="py-2 pr-2">Тип</th>
                  <th className="py-2 pr-2">Сумма</th>
                  <th className="py-2 pr-2">Контрагент</th>
                  <th className="py-2 pr-2">Назначение</th>
                  <th className="py-2">Категория</th>
                </tr>
              </thead>
              <tbody>
                {unclassifiedRows.map((row) => (
                  <tr key={row.id} className="border-b align-top">
                    <td className="py-2 pr-2">{row.business_date}</td>
                    <td className="py-2 pr-2">
                      {directionLabel(row.direction === "in" ? "in" : "out")}
                    </td>
                    <td className="py-2 pr-2">
                      {row.amount} {row.currency}
                    </td>
                    <td className="py-2 pr-2">
                      {formatCounterparty(row.counterparty_name ?? "", row.counterparty_inn ?? "")}
                    </td>
                    <td className="py-2 pr-2">{row.description || "—"}</td>
                    <td className="py-2">
                      <select
                        className="rounded border px-2 py-1 disabled:opacity-50"
                        value={pendingCategory[row.id] ?? ""}
                        disabled={!selection.canWrite || classifyTx.isPending}
                        onChange={(event) =>
                          setPendingCategory((prev) => ({ ...prev, [row.id]: event.target.value }))
                        }
                      >
                        <option value="">— выберите —</option>
                        {(categoryList ?? []).map((cat) => (
                          <option key={cat.id} value={cat.id}>
                            {cat.name} ({cashFlowSectionLabel(cat.cash_flow_section)})
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="ml-2 rounded border px-2 py-1 text-xs disabled:opacity-50"
                        disabled={
                          !selection.canWrite ||
                          !pendingCategory[row.id] ||
                          classifyTx.isPending
                        }
                        onClick={() =>
                          classifyTx.mutate({
                            txId: row.id,
                            version: row.version,
                            categoryId: pendingCategory[row.id],
                          })
                        }
                      >
                        Сохранить
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {unclassifiedHasMore ? (
          <button
            type="button"
            className="mt-3 rounded border px-3 py-1 text-sm"
            onClick={() => void loadMoreUnclassified().catch((exc) => setError(failureMessage(exc)))}
          >
            Показать ещё
          </button>
        ) : null}
      </section>

      <section className="rounded-xl border bg-white p-4" data-testid="rules-block">
        <h2 className="mb-3 text-lg font-semibold">Правила классификации</h2>
        {rules.isLoading ? <p className="text-sm text-slate-600">Загрузка правил…</p> : null}
        {rules.isError ? <p className="text-sm text-red-700">Не удалось загрузить правила.</p> : null}
        <ul className="mb-6 space-y-3">
          {(ruleList ?? []).map((rule) => (
            <li key={rule.id} className="rounded border p-3 text-sm">
              <p className="font-medium">{rule.name}</p>
              <p>Приоритет: {rule.priority}</p>
              <p>Условия: {formatRuleConditionsHuman(rule.conditions)}</p>
              <p>
                Категория:{" "}
                {categoryLabel(rule.actions.category_code, categoryList ?? [])}
              </p>
              <p>Статус: {ruleEnabledLabel(rule.enabled)}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="rounded border px-2 py-1 disabled:opacity-50"
                  disabled={!selection.canWrite || patchRule.isPending || applyRunning}
                  onClick={() => {
                    if (
                      !window.confirm(
                        rule.enabled
                          ? "Отключить правило? Оно не будет применяться при импорте."
                          : "Включить правило?",
                      )
                    ) {
                      return;
                    }
                    patchRule.mutate({ ruleId: rule.id, body: { enabled: !rule.enabled } });
                  }}
                >
                  {rule.enabled ? "Отключить" : "Включить"}
                </button>
                <button
                  type="button"
                  className="rounded border px-2 py-1 disabled:opacity-50"
                  disabled={!selection.canWrite || patchRule.isPending}
                  onClick={() => {
                    const raw = window.prompt("Новый приоритет (1–1000):", String(rule.priority));
                    if (!raw) {
                      return;
                    }
                    const value = Number(raw);
                    if (!Number.isInteger(value) || value < 1 || value > 1000) {
                      setError("Приоритет — целое от 1 до 1000.");
                      return;
                    }
                    patchRule.mutate({ ruleId: rule.id, body: { priority: value } });
                  }}
                >
                  Сменить приоритет
                </button>
                <button
                  type="button"
                  className="rounded border px-2 py-1"
                  disabled={previewRuleId === rule.id}
                  onClick={() => void runPreview(rule.id)}
                >
                  Проверить
                </button>
                <button
                  type="button"
                  className="rounded border px-2 py-1 disabled:opacity-50"
                  disabled={!selection.canWrite || applyRunning}
                  onClick={() => void openApplyDialog(rule)}
                >
                  Применить
                </button>
              </div>
              {previewRuleId === rule.id && previewResult ? (
                <pre className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">
                  {previewResult}
                </pre>
              ) : null}
            </li>
          ))}
        </ul>

        <form className="max-w-lg space-y-3" onSubmit={submitCreateRule}>
          <h3 className="font-medium">Новое правило</h3>
          <label className="block text-sm">
            Название
            <input
              className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
              value={ruleDraft.name}
              disabled={createLocked || createRule.isPending}
              onChange={(event) => setRuleDraft((d) => ({ ...d, name: event.target.value }))}
            />
          </label>
          <label className="block text-sm">
            Приоритет
            <input
              className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
              value={ruleDraft.priority}
              disabled={createLocked || createRule.isPending}
              onChange={(event) => setRuleDraft((d) => ({ ...d, priority: event.target.value }))}
            />
          </label>
          <label className="block text-sm">
            Текст в назначении
            <input
              className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
              value={ruleDraft.conditions.descriptionContains}
              disabled={createLocked || createRule.isPending}
              onChange={(event) =>
                setRuleDraft((d) => ({
                  ...d,
                  conditions: { ...d.conditions, descriptionContains: event.target.value },
                }))
              }
            />
          </label>
          <label className="block text-sm">
            ИНН контрагента
            <input
              className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
              value={ruleDraft.conditions.counterpartyInn}
              disabled={createLocked || createRule.isPending}
              onChange={(event) =>
                setRuleDraft((d) => ({
                  ...d,
                  conditions: { ...d.conditions, counterpartyInn: event.target.value },
                }))
              }
            />
          </label>
          <label className="block text-sm">
            Направление
            <select
              className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
              value={ruleDraft.conditions.direction}
              disabled={createLocked || createRule.isPending}
              onChange={(event) =>
                setRuleDraft((d) => ({
                  ...d,
                  conditions: {
                    ...d.conditions,
                    direction: event.target.value as RuleConditionsDraft["direction"],
                  },
                }))
              }
            >
              <option value="">— любое —</option>
              <option value="in">Поступление</option>
              <option value="out">Списание</option>
            </select>
          </label>
          <div className="flex gap-3">
            <label className="block flex-1 text-sm">
              Сумма от
              <input
                className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
                value={ruleDraft.conditions.amountMin}
                disabled={createLocked || createRule.isPending}
                onChange={(event) =>
                  setRuleDraft((d) => ({
                    ...d,
                    conditions: { ...d.conditions, amountMin: event.target.value },
                  }))
                }
              />
            </label>
            <label className="block flex-1 text-sm">
              Сумма до
              <input
                className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
                value={ruleDraft.conditions.amountMax}
                disabled={createLocked || createRule.isPending}
                onChange={(event) =>
                  setRuleDraft((d) => ({
                    ...d,
                    conditions: { ...d.conditions, amountMax: event.target.value },
                  }))
                }
              />
            </label>
          </div>
          <label className="block text-sm">
            Категория
            <select
              className="mt-1 w-full rounded border px-3 py-2 disabled:opacity-50"
              value={ruleDraft.categoryCode}
              disabled={createLocked || createRule.isPending}
              onChange={(event) => setRuleDraft((d) => ({ ...d, categoryCode: event.target.value }))}
            >
              <option value="">— выберите —</option>
              {(categoryList ?? []).map((cat) => (
                <option key={cat.id} value={cat.code}>
                  {cat.name} ({cashFlowSectionLabel(cat.cash_flow_section)})
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50"
            disabled={!selection.canWrite || createRule.isPending}
          >
            {createAttempt?.phase === "unknown" ? "Повторить отправку" : "Создать правило"}
          </button>
        </form>
      </section>

      {applyDialog ? (
        <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/40 p-4" role="dialog">
          <div className="max-w-md rounded-xl bg-white p-4 text-sm shadow-lg">
            <h3 className="mb-2 text-lg font-semibold">Применить правило «{applyDialog.name}»</h3>
            {applyPreview ? (
              <p className="mb-2">
                Совпадений: {applyPreview.total_matches}. Пропуски: заблокировано{" "}
                {applyPreview.skipped_locked}, уже с категорией {applyPreview.skipped_categorized},
                другой приоритет {applyPreview.skipped_higher_priority}.
              </p>
            ) : null}
            <p className="mb-2 text-amber-900">Массово отменить нельзя.</p>
            {applyProgress ? (
              <p className="mb-2">Применено: {applyProgress.applied}…</p>
            ) : null}
            {applyError ? <p className="mb-2 text-red-700">{applyError}</p> : null}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded border px-3 py-1 disabled:opacity-50"
                disabled={applyRunning}
                onClick={() => {
                  setApplyDialog(null);
                  setApplyPreview(null);
                }}
              >
                Отмена
              </button>
              {applyPaused ? (
                <button
                  type="button"
                  className="rounded bg-slate-900 px-3 py-1 text-white"
                  onClick={() => void runApplyLoop(applyDialog.id, applyCursor)}
                >
                  Продолжить
                </button>
              ) : (
                <button
                  type="button"
                  className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50"
                  disabled={applyRunning}
                  onClick={() => void runApplyLoop(applyDialog.id, null)}
                >
                  {applyRunning ? "Применение…" : "Применить"}
                </button>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </Shell>
  );
}
