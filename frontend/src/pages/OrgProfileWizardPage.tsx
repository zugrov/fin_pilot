import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  listCompanies,
  loadOrganizationProfile,
  loadTaxNormsCurrent,
  patchCompanyProfileFields,
  patchOrganizationProfileDraft,
  WalletRequestError,
  type OrganizationProfile,
} from "../api";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import { Banner } from "../components/system/Banner";
import { StatusChip } from "../components/system/StatusChip";
import { companyDate } from "../lib/forecast";
import { useWritableCompanySelection } from "../lib/companySelection";
import { isOrgProfileReadOnly } from "../lib/orgProfileAccess";
import { fieldErrorsFromUnknown } from "../lib/orgProfileErrors";
import {
  orgProfileApiMessage,
  orgProfileFieldMessage,
  orgProfileSupportBanner,
} from "../lib/orgProfileMessages";
import { formatThresholdLine, priorYearBandLabels } from "../lib/orgProfileTaxNorms";
import {
  buildStep3DraftPatch,
  mapVatQuestionToSnapshot,
  showUsnExemptionThresholdHint,
  snapshotToVatQuestion,
  step3FieldVisibility,
  type VatQuestionId,
} from "../lib/orgProfileVat";

const ORG_FORMS: { value: string; label: string }[] = [
  { value: "unspecified", label: "Не выбрано" },
  { value: "ip", label: "ИП" },
  { value: "ooo", label: "ООО" },
  { value: "ao", label: "АО" },
];

const TAX_SYSTEMS: { value: string; label: string }[] = [
  { value: "unspecified", label: "Не выбрано" },
  { value: "usn", label: "УСН" },
  { value: "osno", label: "ОСНО" },
  { value: "ausn", label: "АУСН" },
  { value: "psn", label: "ПСН" },
  { value: "eshn", label: "ЕСХН" },
  { value: "self_employed", label: "Самозанятый" },
];

const USN_OBJECTS: { value: string; label: string }[] = [
  { value: "unspecified", label: "Не выбрано" },
  { value: "income", label: "Доходы" },
  { value: "income_minus_expense", label: "Доходы минус расходы" },
];

const VAT_QUESTIONS: { value: VatQuestionId; label: string }[] = [
  { value: "general_payer", label: "Да, общий порядок" },
  { value: "usn_special", label: "Да, на УСН со ставкой 5% или 7%" },
  { value: "exemption_145", label: "Нет, освобождён по ст. 145" },
  { value: "not_applicable", label: "Нет, НДС не применяется" },
  { value: "unknown", label: "Не знаю" },
];

function periodMonth(timezone: string): string {
  const local = companyDate(timezone);
  return `${local.slice(0, 7)}-01`;
}

function innLengthHint(inn: string, orgForm: string): string | null {
  const digits = inn.replace(/\D/g, "");
  if (!digits) {
    return null;
  }
  if (digits.length === 12 && orgForm === "ooo") {
    return "12 цифр обычно у ИП; для ООО чаще 10 цифр.";
  }
  if (digits.length === 10 && orgForm === "ip") {
    return "10 цифр обычно у ООО; для ИП чаще 12 цифр.";
  }
  return null;
}

type SaveVars = { advance: boolean };

export function OrgProfileWizardPage() {
  const client = useQueryClient();
  const [step, setStep] = useState(1);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [step3Saved, setStep3Saved] = useState(false);
  const [innDraft, setInnDraft] = useState("");
  const [orgForm, setOrgForm] = useState("unspecified");
  const [taxSystem, setTaxSystem] = useState("unspecified");
  const [usnObject, setUsnObject] = useState("unspecified");
  const [vatAnswer, setVatAnswer] = useState<VatQuestionId>("unknown");
  const [vatRate, setVatRate] = useState("22");
  const [pricesIncludeVat, setPricesIncludeVat] = useState("unknown");
  const [isNewOrg, setIsNewOrg] = useState<boolean | null>(null);
  const [revenueBand, setRevenueBand] = useState("unknown");

  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const onCompanyChanged = useCallback(() => {
    setError("");
    setFieldErrors({});
    setStep(1);
    setStep3Saved(false);
  }, []);
  const selection = useWritableCompanySelection(companies, { onCompanyChanged });
  const { companyId, company } = selection;
  const period = company?.timezone ? periodMonth(company.timezone) : undefined;

  const profile = useQuery({
    queryKey: ["organization-profile", companyId, period],
    queryFn: () => loadOrganizationProfile(companyId ?? "", period),
    enabled: Boolean(companyId && period),
  });

  const readOnly = isOrgProfileReadOnly(profile.data?.can_write);

  const asOf = company?.timezone ? companyDate(company.timezone) : "";
  const taxNorms = useQuery({
    queryKey: ["tax-norms", asOf],
    queryFn: () => loadTaxNormsCurrent(asOf),
    enabled: Boolean(asOf) && step >= 3,
  });

  const syncFromProfile = useCallback((data: OrganizationProfile) => {
    setOrgForm(data.org_form);
    setTaxSystem(data.tax_system);
    setUsnObject(data.usn_tax_object);
    setVatAnswer(snapshotToVatQuestion(data));
    setVatRate(data.vat_default_rate ?? "22");
    setPricesIncludeVat(data.prices_include_vat);
    setIsNewOrg(data.is_new_organization);
    setRevenueBand(data.prior_year_revenue_band);
    setFieldErrors(data.confirm_readiness?.field_errors ?? {});
  }, []);

  useEffect(() => {
    if (!profile.data) {
      return;
    }
    syncFromProfile(profile.data);
  }, [profile.data, syncFromProfile]);

  useEffect(() => {
    const match = companies.data?.companies?.find((item) => item.id === companyId);
    if (match?.inn !== undefined) {
      setInnDraft(match.inn ?? "");
    }
  }, [companies.data?.companies, companyId]);

  const bandLabels = useMemo(
    () => priorYearBandLabels(taxNorms.data?.values ?? {}),
    [taxNorms.data?.values],
  );

  const visibility = step3FieldVisibility({
    tax_system: taxSystem,
    vat_status: mapVatQuestionToSnapshot(vatAnswer, { taxSystem, vatDefaultRate: vatRate })
      .vat_status,
    is_new_organization: isNewOrg,
  });

  const thresholdHint = showUsnExemptionThresholdHint({
    taxSystem,
    revenueBand,
    vatAnswer,
  });

  const supportText = orgProfileSupportBanner(profile.data?.support_code);
  const supportTone =
    profile.data?.support_level === "unsupported"
      ? "danger"
      : profile.data?.support_level === "partial"
        ? "warn"
        : "info";

  const saveStep = useMutation({
    mutationFn: async ({ advance }: SaveVars) => {
      if (!companyId) {
        throw new Error("Выберите организацию");
      }
      if (readOnly) {
        return;
      }
      if (step === 1) {
        const match = companies.data?.companies?.find((item) => item.id === companyId);
        const prevInn = match?.inn ?? "";
        if (innDraft.trim() !== (prevInn ?? "").trim()) {
          await patchCompanyProfileFields(companyId, { inn: innDraft.trim() || null });
          await client.invalidateQueries({ queryKey: ["companies"] });
        }
        await patchOrganizationProfileDraft(companyId, { org_form: orgForm });
      } else if (step === 2) {
        const body: Record<string, unknown> = { tax_system: taxSystem };
        if (taxSystem === "usn") {
          body.usn_tax_object = usnObject;
        }
        await patchOrganizationProfileDraft(companyId, body);
      } else if (step === 3) {
        const body = buildStep3DraftPatch({
          taxSystem,
          vatAnswer,
          vatRate,
          pricesIncludeVat,
          isNewOrg,
          revenueBand,
        });
        await patchOrganizationProfileDraft(companyId, body);
      }
      return advance;
    },
    onSuccess: async (advance) => {
      setError("");
      setFieldErrors({});
      await client.invalidateQueries({ queryKey: ["organization-profile", companyId] });
      if (step < 3 && advance) {
        setStep(step + 1);
      }
      if (step === 3) {
        setStep3Saved(true);
      }
    },
    onError: (exc) => {
      const serverFields = fieldErrorsFromUnknown(exc);
      if (Object.keys(serverFields).length > 0) {
        setFieldErrors(serverFields);
      }
      if (exc instanceof WalletRequestError) {
        setError(orgProfileApiMessage(exc.code, exc.message));
        return;
      }
      setError(exc instanceof Error ? exc.message : "Ошибка сохранения");
    },
  });

  const onNext = () => {
    setError("");
    setStep3Saved(false);
    saveStep.mutate({ advance: true });
  };

  const onSaveStep3 = () => {
    setError("");
    saveStep.mutate({ advance: false });
  };

  const onBack = () => {
    setError("");
    setStep3Saved(false);
    setStep((value) => Math.max(1, value - 1));
  };

  const renderFieldErrors = (field: string) =>
    (fieldErrors[field] ?? []).map((code) => (
      <p key={`${field}-${code}`} className="text-caption text-danger">
        {orgProfileFieldMessage(field, code)}
      </p>
    ));

  const statusChip = profile.data?.is_confirmed ? (
    <StatusChip tone="ok">Подтверждён</StatusChip>
  ) : (
    <StatusChip tone="warn">Черновик</StatusChip>
  );

  return (
    <Shell title="Профиль организации">
      <p className="mb-4 text-sm text-ink-muted">Настройка режима и налоговых правил.</p>
      <CompanyWritePicker
        listPhase={selection.listPhase}
        list={selection.list}
        value={selection.selectValue}
        needsPlaceholder={selection.needsPlaceholder}
        disabled={selection.pickerDisabled || saveStep.isPending}
        onSelect={selection.onSelect}
      />
      {profile.isLoading ? <p className="text-body text-muted">Загрузка профиля…</p> : null}
      {profile.isError ? (
        <Banner tone="danger" label="Ошибка сети">
          Не удалось загрузить профиль.{" "}
          <button type="button" className="underline" onClick={() => profile.refetch()}>
            Повторить
          </button>
        </Banner>
      ) : null}
      {readOnly ? (
        <Banner tone="info" label="Только просмотр">
          Изменять профиль могут владелец и бухгалтер с подтверждённой почтой.
        </Banner>
      ) : null}
      {profile.data ? (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {statusChip}
          {import.meta.env.DEV ? (
            <span className="text-caption text-muted">Шаг {step} из 3</span>
          ) : null}
        </div>
      ) : null}
      {supportText ? (
        <div className="mb-4">
          <Banner tone={supportTone as "warn" | "danger" | "info"} label="Поддержка профиля">
            {supportText}
          </Banner>
        </div>
      ) : null}
      {taxNorms.data?.needs_review_banner ? (
        <div className="mb-4">
          <Banner tone="warn" label="Справочник на проверке">
            Цифры порогов — ориентиры. Уточните у бухгалтера перед решением.
          </Banner>
        </div>
      ) : null}
      {error ? (
        <div className="mb-4">
          <Banner tone="danger">{error}</Banner>
        </div>
      ) : null}

      {step === 1 ? (
        <section className="space-y-4 rounded-card border border-line bg-surface p-card">
          <h2 className="text-heading">Форма и ИНН</h2>
          <label className="block text-body">
            Организационно-правовая форма
            <select
              className="mt-1 w-full rounded border border-line px-3 py-2"
              value={orgForm}
              disabled={readOnly}
              onChange={(event) => setOrgForm(event.target.value)}
            >
              {ORG_FORMS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {renderFieldErrors("org_form")}
          <label className="block text-body">
            ИНН
            <input
              className="mt-1 w-full rounded border border-line px-3 py-2"
              value={innDraft}
              disabled={readOnly}
              onChange={(event) => setInnDraft(event.target.value)}
              inputMode="numeric"
              maxLength={12}
            />
          </label>
          {innLengthHint(innDraft, orgForm) ? (
            <p className="text-caption text-warn">{innLengthHint(innDraft, orgForm)}</p>
          ) : null}
          {renderFieldErrors("inn")}
        </section>
      ) : null}

      {step === 2 ? (
        <section className="space-y-4 rounded-card border border-line bg-surface p-card">
          <h2 className="text-heading">Система налогообложения</h2>
          <label className="block text-body">
            Режим
            <select
              className="mt-1 w-full rounded border border-line px-3 py-2"
              value={taxSystem}
              disabled={readOnly}
              onChange={(event) => setTaxSystem(event.target.value)}
            >
              {TAX_SYSTEMS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {renderFieldErrors("tax_system")}
          {taxSystem === "usn" ? (
            <label className="block text-body">
              Объект УСН
              <select
                className="mt-1 w-full rounded border border-line px-3 py-2"
                value={usnObject}
                disabled={readOnly}
                onChange={(event) => setUsnObject(event.target.value)}
              >
                {USN_OBJECTS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-caption text-muted">
                «Доходы» или «Доходы минус расходы» — как в вашей учётной политике.
              </span>
            </label>
          ) : null}
          {renderFieldErrors("usn_tax_object")}
        </section>
      ) : null}

      {step === 3 ? (
        <section className="space-y-4 rounded-card border border-line bg-surface p-card">
          <h2 className="text-heading">НДС и пороги</h2>
          {taxNorms.data ? (
            <p className="text-caption text-muted">{formatThresholdLine(taxNorms.data.values)}</p>
          ) : null}
          <fieldset className="space-y-2">
            <legend className="text-body font-medium">Вы платите НДС?</legend>
            {VAT_QUESTIONS.map((item) => (
              <label key={item.value} className="flex items-center gap-2 text-body">
                <input
                  type="radio"
                  name="vat-question"
                  checked={vatAnswer === item.value}
                  disabled={readOnly}
                  onChange={() => {
                    setVatAnswer(item.value);
                    setStep3Saved(false);
                  }}
                />
                {item.label}
              </label>
            ))}
          </fieldset>
          {renderFieldErrors("vat_status")}
          {renderFieldErrors("vat_regime_detail")}
          {visibility.showVatRate ? (
            <label className="block text-body">
              Ставка НДС по умолчанию
              <select
                className="mt-1 w-full rounded border border-line px-3 py-2"
                value={vatRate}
                disabled={readOnly}
                onChange={(event) => setVatRate(event.target.value)}
              >
                <option value="22">22%</option>
                <option value="10">10%</option>
                <option value="0">0%</option>
              </select>
            </label>
          ) : null}
          {renderFieldErrors("vat_default_rate")}
          <label className="block text-body">
            Цены в учёте с НДС?
            <select
              className="mt-1 w-full rounded border border-line px-3 py-2"
              value={pricesIncludeVat}
              disabled={readOnly}
              onChange={(event) => setPricesIncludeVat(event.target.value)}
            >
              <option value="unknown">Не знаю</option>
              <option value="yes">Да</option>
              <option value="no">Нет</option>
            </select>
          </label>
          {renderFieldErrors("prices_include_vat")}
          <label className="block text-body">
            Новая организация (не было выручки в прошлом году)?
            <select
              className="mt-1 w-full rounded border border-line px-3 py-2"
              value={isNewOrg === null ? "unknown" : isNewOrg ? "yes" : "no"}
              disabled={readOnly}
              onChange={(event) => {
                const v = event.target.value;
                if (v === "unknown") {
                  setIsNewOrg(null);
                } else {
                  setIsNewOrg(v === "yes");
                }
                setStep3Saved(false);
              }}
            >
              <option value="unknown">Не указано</option>
              <option value="yes">Да</option>
              <option value="no">Нет</option>
            </select>
          </label>
          {visibility.showRevenueBand ? (
            <label className="block text-body">
              Выручка прошлого года
              <select
                className="mt-1 w-full rounded border border-line px-3 py-2"
                value={revenueBand}
                disabled={readOnly}
                onChange={(event) => {
                  setRevenueBand(event.target.value);
                  setStep3Saved(false);
                }}
              >
                <option value="unknown">Не указано</option>
                {Object.entries(bandLabels).map(([code, label]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {renderFieldErrors("prior_year_revenue_band")}
          {thresholdHint ? (
            <Banner tone="info" label="Подсказка по НДС">
              Для УСН с выручкой прошлого года до порога обычно выбирают «Нет, освобождён по
              ст. 145».
              <div className="mt-2">
                <button
                  type="button"
                  className="rounded border border-line px-3 py-1 min-h-tap"
                  disabled={readOnly}
                  onClick={() => {
                    setVatAnswer("exemption_145");
                    setStep3Saved(false);
                  }}
                >
                  Выбрать
                </button>
              </div>
            </Banner>
          ) : null}
          <p className="text-caption text-muted">
            Освобождение по ст. 145 — отсутствие обязанности исчислять НДС, а не нулевая ставка
            в ценах.
          </p>
        </section>
      ) : null}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="rounded border border-line px-4 py-2 min-h-tap"
          disabled={step === 1 || saveStep.isPending}
          onClick={onBack}
        >
          Назад
        </button>
        {step < 3 ? (
          <button
            type="button"
            className="rounded bg-accent px-4 py-2 text-on-accent min-h-tap"
            disabled={readOnly || saveStep.isPending || !companyId}
            onClick={onNext}
          >
            {saveStep.isPending ? "Сохраняем…" : "Далее"}
          </button>
        ) : (
          <>
            <button
              type="button"
              className="rounded bg-accent px-4 py-2 text-on-accent min-h-tap"
              disabled={readOnly || saveStep.isPending || !companyId}
              onClick={onSaveStep3}
            >
              {saveStep.isPending ? "Сохраняем…" : "Сохранить"}
            </button>
            {step3Saved ? <span className="text-body text-muted">Сохранено</span> : null}
          </>
        )}
      </div>
    </Shell>
  );
}
