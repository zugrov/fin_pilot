import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { listCompanies, loadPlanFact } from "../api";
import { Shell } from "../components/Shell";
import {
  amountText,
  basisLabel,
  calculationCaption,
  cashBudgetNote,
  defaultReportDate,
  draftDisabledReason,
  futureFactNote,
  interimNote,
  matchesPlanFact,
  monthEnd,
  monthLabel,
  planFactText,
  salesFactNote,
  versionStatusLabel,
} from "../lib/budget";
import { companyDate as firmDate } from "../lib/forecast";

export function BudgetsPage() {
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [pickedDate, setPickedDate] = useState<string | null>(null);
  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const list = companies.data?.companies ?? [];
  const preferred = sessionStorage.getItem("fp_company_id");
  const company =
    list.find((item) => item.id === pickedId) ??
    list.find((item) => item.id === preferred) ??
    list[0];
  const reportDate = pickedDate || (company ? defaultReportDate(company.timezone ?? "") : "");
  const fact = useQuery({
    queryKey: ["plan-fact", company?.id, reportDate],
    queryFn: () => loadPlanFact(company?.id ?? "", reportDate),
    enabled: Boolean(company && reportDate),
  });
  const current = matchesPlanFact(fact.data, company?.id, reportDate) ? fact.data : null;
  const today = company ? firmDate(company.timezone ?? "") : "";
  const cash = current?.bases.find((item) => item.basis === "cash");

  return (
    <Shell>
      <h1 className="mb-2 text-xl font-semibold">Бюджет</h1>
      <p className="mb-4 text-sm text-slate-600">
        Это план, не движение денег и не прогноз.
      </p>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        {list.length > 0 ? (
          <label className="text-sm">
            Фирма
            <select
              className="mt-1 block rounded border px-3 py-1"
              value={company?.id ?? ""}
              onChange={(event) => setPickedId(event.target.value)}
            >
              {list.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="text-sm">
          Дата среза
          <input
            className="mt-1 block rounded border px-3 py-1"
            type="date"
            value={reportDate}
            onChange={(event) => setPickedDate(event.target.value)}
          />
        </label>
      </div>
      {reportDate ? (
        <p className="mb-3 text-sm text-slate-600">{calculationCaption(reportDate)}</p>
      ) : null}
      {fact.isLoading || fact.isFetching ? <p>Загрузка</p> : null}
      {fact.isError ? <p className="text-red-700">Не удалось посчитать план-факт.</p> : null}
      {current && !fact.isFetching && !fact.isError ? (
        <>
          {cashBudgetNote(cash?.status) ? (
            <p className="mb-3 text-sm">{cashBudgetNote(cash?.status)}</p>
          ) : null}
          {current.bases.map((basis) => (
            <section key={basis.basis} className="mb-4 rounded-xl border bg-white p-4">
              <p className="text-sm text-slate-600">{basisLabel(basis.basis)}</p>
              {basis.status === "unavailable" && basis.basis !== "cash" ? (
                <p>Нет утверждённого бюджета</p>
              ) : null}
              <ul className="mt-2 space-y-3">
                {basis.lines.map((line) => {
                  const end =
                    basis.year && line.month ? monthEnd(basis.year, line.month) : null;
                  return (
                    <li key={line.line_id ?? `${line.metric_type}-${line.month}`}>
                      <p>
                        {monthLabel(basis.year, line.month)},{" "}
                        {versionStatusLabel(basis.version_status)}
                      </p>
                      <p>План месяца: {amountText(line.plan_month)}</p>
                      <p>План на дату: {amountText(line.plan_to_date)}</p>
                      <p>Факт: {amountText(line.fact)}</p>
                      <p>Отклонение: {amountText(line.delta)}</p>
                      <p>Процент отклонения: {amountText(line.percent)}</p>
                      <p>{planFactText(line.status, line.fact, line.percent)}</p>
                      {basis.basis === "revenue" && salesFactNote(basis.completeness) ? (
                        <p>{salesFactNote(basis.completeness)}</p>
                      ) : null}
                      {interimNote(today, current.report_date, end) ? (
                        <p>{interimNote(today, current.report_date, end)}</p>
                      ) : null}
                      {futureFactNote(today, current.report_date) ? (
                        <p>{futureFactNote(today, current.report_date)}</p>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </>
      ) : null}
      <p className="mb-3 text-sm text-slate-600">{draftDisabledReason()}</p>
      <button type="button" className="rounded border px-3 py-2" disabled>
        Создать черновик
      </button>
    </Shell>
  );
}
