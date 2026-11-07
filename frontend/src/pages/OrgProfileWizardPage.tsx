import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  confirmOrganizationProfileVersion,
  listCompanies,
  listOrganizationProfileVersions,
  loadOrganizationProfile,
  loadTaxNormsCurrent,
  patchCompanyProfileFields,
  patchOrganizationProfileDraft,
  postOrganizationProfileVersion,
  WalletRequestError,
  type OrganizationProfile,
} from "../api";
import { OrgProfileCardPanel } from "../components/orgProfile/OrgProfileCardPanel";
import { OrgProfileSummarySection } from "../components/orgProfile/OrgProfileSummarySection";
import { CompanyWritePicker } from "../components/CompanyWritePicker";
import { Shell } from "../components/Shell";
import { Banner } from "../components/system/Banner";
import { StatusChip } from "../components/system/StatusChip";
import { formatDate } from "../lib/dates";
import { companyDate } from "../lib/forecast";
import {
  defaultEffectiveFromMonth,
  monthInputMinAfterVersion,
} from "../lib/orgProfileEffectiveFrom";
import { versionCreateSnapshotSource } from "../lib/orgProfileVersionCreate";
import { buildVersionCreateBody } from "../lib/orgProfileVersionSnapshot";
import {
  canConfirmOrganizationProfile,
  confirmTargetVersionId,
  currentPeriodMonth,
  isFutureUnconfirmedDraft,
  latestProfileVersion,
  maxYearMonth,
  shouldShowWizard,
  wizardProfilePeriod,
  wizardWriteActionsVisible,
} from "../lib/orgProfileWizardPlan";
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

const ACCOUNTING_SOURCES: { value: string; label: string }[] = [
  { value: "unspecified", label: "Не выбрано" },
  { value: "onec", label: "1С" },
  { value: "cloud", label: "Облачная бухгалтерия" },
  { value: "book_csv", label: "Книга / CSV" },
];

const MONEY_CHANNELS: { value: string; label: string }[] = [
  { value: "bank", label: "Банк" },
  { value: "acquiring", label: "Эквайринг" },
  { value: "cash", label: "Касса" },
  { value: "other", label: "Прочее" },
];

const INDUSTRY_SPHERES: { value: string; label: string }[] = [
  { value: "unspecified", label: "Не выбрано" },
  { value: "trade", label: "Торговля" },
  { value: "services", label: "Услуги" },
  { value: "production", label: "Производство" },
  { value: "mixed", label: "Смешанная" },
];

const MONTH_CLOSE_POLICIES: { value: string; label: string }[] = [
  { value: "unknown", label: "Не выбрано" },
  { value: "calendar_month_end", label: "Конец календарного месяца" },
  { value: "manual", label: "Вручную" },
  { value: "other", label: "Иное" },
];

const REVENUE_METHODS: { value: string; label: string }[] = [
  { value: "unknown", label: "Не выбрано" },
  { value: "accrual", label: "Начисление" },
  { value: "cash", label: "Кассовый метод" },
  { value: "other", label: "Иное" },
];

const VAT_QUESTIONS: { value: VatQuestionId; label: string }[] = [
  { value: "general_payer", label: "Да, общий порядок" },
  { value: "usn_special", label: "Да, на УСН со ставкой 5% или 7%" },
  { value: "exemption_145", label: "Нет, освобождён по ст. 145" },
  { value: "not_applicable", label: "Нет, НДС не применяется" },
  { value: "unknown", label: "Не знаю" },
];

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
  const [accountingSource, setAccountingSource] = useState("unspecified");
  const [moneyChannels, setMoneyChannels] = useState<string[]>([]);
  const [industrySphere, setIndustrySphere] = useState("unspecified");
  const [monthClosePolicy, setMonthClosePolicy] = useState("unknown");
  const [revenueRecognition, setRevenueRecognition] = useState("unknown");
  const [wizardOpen, setWizardOpen] = useState(true);
  const [changeModalOpen, setChangeModalOpen] = useState(false);
  const [changeReason, setChangeReason] = useState("");
  const [effectiveFromMonth, setEffectiveFromMonth] = useState("");
  const changeModeButtonRef = useRef<HTMLButtonElement>(null);

  const companies = useQuery({ queryKey: ["companies"], queryFn: listCompanies });
  const onCompanyChanged = useCallback(() => {
    setError("");
    setFieldErrors({});
    setStep(1);
    setStep3Saved(false);
    setWizardOpen(true);
    setChangeModalOpen(false);
  }, []);
  const selection = useWritableCompanySelection(companies, { onCompanyChanged });
  const { companyId, company } = selection;

  const versions = useQuery({
    queryKey: ["organization-profile-versions", companyId],
    queryFn: () => listOrganizationProfileVersions(companyId ?? ""),
    enabled: Boolean(companyId),
  });

  const latestVersion = useMemo(
    () => latestProfileVersion(versions.data?.versions),
    [versions.data?.versions],
  );

  const currentPeriod = useMemo(
    () => (company?.timezone ? currentPeriodMonth(company.timezone) : undefined),
    [company?.timezone],
  );

  const wizardPeriod = useMemo(() => {
    if (!company?.timezone) {
      return undefined;
    }
    return wizardProfilePeriod(company.timezone, latestVersion?.effective_from);
  }, [company?.timezone, latestVersion?.effective_from]);

  const profile = useQuery({
    queryKey: ["organization-profile", companyId, wizardPeriod],
    queryFn: () => loadOrganizationProfile(companyId ?? "", wizardPeriod),
    enabled: Boolean(companyId && wizardPeriod),
  });

  const cardProfile = useQuery({
    queryKey: ["organization-profile", companyId, currentPeriod],
    queryFn: () => loadOrganizationProfile(companyId ?? "", currentPeriod),
    enabled: Boolean(companyId && currentPeriod),
  });

  const readOnly = isOrgProfileReadOnly(profile.data?.can_write);
  const writeActions = wizardWriteActionsVisible(profile.data?.can_write);
  const showCard = Boolean(cardProfile.data?.is_confirmed);
  const futureDraft = isFutureUnconfirmedDraft(latestVersion, currentPeriod ?? "");

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
    setAccountingSource(data.accounting_source);
    setMoneyChannels((data.money_channels ?? []).filter((code) => code !== "unspecified"));
    setIndustrySphere(data.industry_sphere);
    setMonthClosePolicy(data.month_close_policy);
    setRevenueRecognition(data.revenue_recognition_method);
    setFieldErrors(data.confirm_readiness?.field_errors ?? {});
  }, []);

  useEffect(() => {
    if (!profile.data) {
      return;
    }
    syncFromProfile(profile.data);
  }, [profile.data, syncFromProfile]);

  useEffect(() => {
    if (!latestVersion) {
      setWizardOpen(true);
      return;
    }
    setWizardOpen(shouldShowWizard(latestVersion));
  }, [latestVersion?.version_id, latestVersion?.is_confirmed]);

  useEffect(() => {
    if (!company?.timezone || !latestVersion) {
      return;
    }
    const minMonth = monthInputMinAfterVersion(latestVersion.effective_from);
    const suggested = defaultEffectiveFromMonth(company.timezone).slice(0, 7);
    setEffectiveFromMonth(maxYearMonth(suggested, minMonth));
  }, [company?.timezone, companyId, latestVersion?.effective_from]);

  useEffect(() => {
    if (!changeModalOpen) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setChangeModalOpen(false);
        changeModeButtonRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [changeModalOpen]);

  const closeChangeModal = () => {
    setChangeModalOpen(false);
    changeModeButtonRef.current?.focus();
  };

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
      } else if (step === 4) {
        await patchOrganizationProfileDraft(companyId, { accounting_source: accountingSource });
      } else if (step === 5) {
        await patchOrganizationProfileDraft(companyId, {
          money_channels: moneyChannels.length ? moneyChannels : ["unspecified"],
          industry_sphere: industrySphere,
        });
      }
      return advance;
    },
    onSuccess: async (advance) => {
      setError("");
      setFieldErrors({});
      await client.invalidateQueries({ queryKey: ["organization-profile", companyId] });
      if (step < 6 && advance) {
        setStep(step + 1);
      }
      if (step === 3 && !advance) {
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

  const toggleMoneyChannel = (code: string) => {
    setMoneyChannels((current) =>
      current.includes(code) ? current.filter((item) => item !== code) : [...current, code],
    );
  };

  const saveAndCheckStep6 = useMutation({
    mutationFn: async () => {
      if (!companyId || !wizardPeriod) {
        throw new Error("Выберите организацию");
      }
      await patchOrganizationProfileDraft(companyId, {
        month_close_policy: monthClosePolicy,
        revenue_recognition_method: revenueRecognition,
      });
      return loadOrganizationProfile(companyId, wizardPeriod);
    },
    onSuccess: (data) => {
      setError("");
      setFieldErrors({});
      client.setQueryData(["organization-profile", companyId, wizardPeriod], data);
      syncFromProfile(data);
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

  const confirmProfile = useMutation({
    mutationFn: async () => {
      if (!companyId) {
        throw new Error("Выберите организацию");
      }
      const versionId = confirmTargetVersionId(latestVersion, profile.data?.version_id);
      if (!versionId) {
        throw new Error("Версия профиля не найдена");
      }
      return confirmOrganizationProfileVersion(companyId, versionId, crypto.randomUUID());
    },
    onSuccess: async (data) => {
      setError("");
      setWizardOpen(false);
      if (companyId && wizardPeriod) {
        client.setQueryData(["organization-profile", companyId, wizardPeriod], data);
      }
      if (companyId && currentPeriod) {
        client.setQueryData(["organization-profile", companyId, currentPeriod], {
          ...data,
          period: currentPeriod,
          profile_unconfirmed: false,
          is_confirmed: true,
        });
      }
      await client.invalidateQueries({ queryKey: ["organization-profile", companyId] });
      await client.invalidateQueries({ queryKey: ["organization-profile-versions", companyId] });
    },
    onError: async (exc) => {
      if (exc instanceof WalletRequestError) {
        setError(orgProfileApiMessage(exc.code, exc.message));
        if (exc.code === "already_confirmed" || exc.status === 409) {
          await profile.refetch();
          await versions.refetch();
        }
        return;
      }
      setError(exc instanceof Error ? exc.message : "Не удалось подтвердить профиль");
    },
  });

  const createVersion = useMutation({
    mutationFn: async () => {
      if (!companyId) {
        throw new Error("Выберите организацию");
      }
      const snapshotSource = versionCreateSnapshotSource(profile.data, cardProfile.data);
      if (!snapshotSource) {
        throw new Error("Профиль не загружен");
      }
      const effectiveFrom = `${effectiveFromMonth}-01`;
      const body = buildVersionCreateBody(snapshotSource, effectiveFrom, changeReason);
      return postOrganizationProfileVersion(companyId, body, crypto.randomUUID());
    },
    onSuccess: async () => {
      setChangeModalOpen(false);
      setChangeReason("");
      setWizardOpen(true);
      setStep(1);
      await client.invalidateQueries({ queryKey: ["organization-profile", companyId] });
      await client.invalidateQueries({ queryKey: ["organization-profile-versions", companyId] });
    },
    onError: (exc) => {
      if (exc instanceof WalletRequestError) {
        setError(orgProfileApiMessage(exc.code, exc.message));
        return;
      }
      setError(exc instanceof Error ? exc.message : "Не удалось создать версию");
    },
  });

  const renderFieldErrors = (field: string) =>
    (fieldErrors[field] ?? []).map((code) => (
      <p key={`${field}-${code}`} className="text-caption text-danger">
        {orgProfileFieldMessage(field, code)}
      </p>
    ));

  const wizardStatusChip = profile.data?.is_confirmed ? (
    <StatusChip tone="ok">
      Подтверждён
      {profile.data.confirmed_at
        ? ` · ${formatDate(profile.data.confirmed_at.slice(0, 10))}`
        : ""}
    </StatusChip>
  ) : (
    <StatusChip tone="warn">Черновик</StatusChip>
  );

  const canConfirm = canConfirmOrganizationProfile(
    profile.data,
    monthClosePolicy,
    revenueRecognition,
  );
  const minEffectiveMonth = latestVersion
    ? monthInputMinAfterVersion(latestVersion.effective_from)
    : undefined;

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
      {wizardOpen && profile.data ? (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {wizardStatusChip}
          {futureDraft && latestVersion ? (
            <span className="text-body text-warn">
              Черновик нового режима с {formatDate(latestVersion.effective_from)}
            </span>
          ) : null}
          {import.meta.env.DEV ? (
            <span className="text-caption text-muted">Шаг {step} из 6 (P3b)</span>
          ) : null}
        </div>
      ) : null}
      {showCard && cardProfile.data ? (
        <OrgProfileCardPanel
          profile={cardProfile.data}
          versions={versions.data?.versions}
          companyTimeZone={company?.timezone ?? "Europe/Moscow"}
          readOnly={readOnly}
          changeModeButtonRef={changeModeButtonRef}
          onChangeMode={() => {
            setError("");
            if (company?.timezone && latestVersion) {
              const minMonth = monthInputMinAfterVersion(latestVersion.effective_from);
              const suggested = defaultEffectiveFromMonth(company.timezone).slice(0, 7);
              setEffectiveFromMonth(maxYearMonth(suggested, minMonth));
            }
            setChangeModalOpen(true);
          }}
        />
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

      {wizardOpen && step === 1 ? (
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

      {wizardOpen && step === 2 ? (
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

      {wizardOpen && step === 3 ? (
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

      {wizardOpen && step === 4 ? (
        <section className="space-y-4 rounded-card border border-line bg-surface p-card">
          <h2 className="text-heading">Источник учёта</h2>
          <label className="block text-body">
            Откуда будут выгрузки
            <select
              className="mt-1 w-full rounded border border-line px-3 py-2"
              value={accountingSource}
              disabled={readOnly}
              onChange={(event) => setAccountingSource(event.target.value)}
            >
              {ACCOUNTING_SOURCES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {renderFieldErrors("accounting_source")}
        </section>
      ) : null}

      {wizardOpen && step === 5 ? (
        <section className="space-y-4 rounded-card border border-line bg-surface p-card">
          <h2 className="text-heading">Каналы денег и сфера</h2>
          <fieldset className="space-y-2">
            <legend className="text-body font-medium">Каналы денег</legend>
            {MONEY_CHANNELS.map((item) => (
              <label key={item.value} className="flex items-center gap-2 text-body">
                <input
                  type="checkbox"
                  checked={moneyChannels.includes(item.value)}
                  disabled={readOnly}
                  onChange={() => toggleMoneyChannel(item.value)}
                />
                {item.label}
              </label>
            ))}
          </fieldset>
          {renderFieldErrors("money_channels")}
          <label className="block text-body">
            Сфера деятельности
            <select
              className="mt-1 w-full rounded border border-line px-3 py-2"
              value={industrySphere}
              disabled={readOnly}
              onChange={(event) => setIndustrySphere(event.target.value)}
            >
              {INDUSTRY_SPHERES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {renderFieldErrors("industry_sphere")}
        </section>
      ) : null}

      {wizardOpen && step === 6 ? (
        <section className="space-y-4 rounded-card border border-line bg-surface p-card">
          <h2 className="text-heading">Закрытие месяца и выручка</h2>
          <label className="block text-body">
            Закрытие месяца в учёте
            <select
              className="mt-1 w-full rounded border border-line px-3 py-2"
              value={monthClosePolicy}
              disabled={readOnly}
              onChange={(event) => setMonthClosePolicy(event.target.value)}
            >
              {MONTH_CLOSE_POLICIES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {renderFieldErrors("month_close_policy")}
          <label className="block text-body">
            Признание выручки
            <select
              className="mt-1 w-full rounded border border-line px-3 py-2"
              value={revenueRecognition}
              disabled={readOnly}
              onChange={(event) => setRevenueRecognition(event.target.value)}
            >
              {REVENUE_METHODS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {renderFieldErrors("revenue_recognition_method")}
          {profile.data ? <OrgProfileSummarySection profile={profile.data} showMissing /> : null}
        </section>
      ) : null}

      {wizardOpen && writeActions ? (
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button
            type="button"
            className="rounded border border-line px-4 py-2 min-h-tap"
            disabled={step === 1 || saveStep.isPending || confirmProfile.isPending}
            onClick={onBack}
          >
            Назад
          </button>
          {step < 6 && step !== 3 ? (
            <button
              type="button"
              className="rounded bg-accent px-4 py-2 text-on-accent min-h-tap"
              disabled={readOnly || saveStep.isPending || !companyId}
              onClick={onNext}
            >
              {saveStep.isPending ? "Сохраняем…" : "Далее"}
            </button>
          ) : null}
          {step === 3 ? (
            <>
              <button
                type="button"
                className="rounded bg-accent px-4 py-2 text-on-accent min-h-tap"
                disabled={readOnly || saveStep.isPending || !companyId}
                onClick={onSaveStep3}
              >
                {saveStep.isPending ? "Сохраняем…" : "Сохранить"}
              </button>
              <button
                type="button"
                className="rounded border border-line px-4 py-2 min-h-tap"
                disabled={readOnly || saveStep.isPending || !companyId}
                onClick={onNext}
              >
                Далее
              </button>
              {step3Saved ? <span className="text-body text-muted">Сохранено</span> : null}
            </>
          ) : null}
          {step === 6 ? (
            <>
              <button
                type="button"
                className="rounded border border-line px-4 py-2 min-h-tap"
                disabled={saveAndCheckStep6.isPending || confirmProfile.isPending}
                onClick={() => saveAndCheckStep6.mutate()}
              >
                {saveAndCheckStep6.isPending ? "Сохраняем…" : "Сохранить и проверить"}
              </button>
              <button
                type="button"
                className="rounded bg-accent px-4 py-2 text-on-accent min-h-tap"
                disabled={!canConfirm || confirmProfile.isPending || saveAndCheckStep6.isPending}
                onClick={() => confirmProfile.mutate()}
              >
                {confirmProfile.isPending ? "Подтверждаем…" : "Подтвердить профиль"}
              </button>
              {!canConfirm ? (
                <span className="text-caption text-muted">Сохраните изменения</span>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}

      {changeModalOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
          <div
            className="w-full max-w-md space-y-4 rounded-card border border-line bg-surface p-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="change-mode-title"
          >
            <h2 id="change-mode-title" className="text-heading">
              Изменить режим с даты
            </h2>
            <label className="block text-body">
              Месяц начала действия
              <input
                type="month"
                className="mt-1 w-full rounded border border-line px-3 py-2"
                value={effectiveFromMonth}
                min={minEffectiveMonth}
                onChange={(event) => setEffectiveFromMonth(event.target.value)}
              />
            </label>
            <label className="block text-body">
              Причина изменения
              <textarea
                className="mt-1 w-full rounded border border-line px-3 py-2"
                rows={3}
                maxLength={500}
                value={changeReason}
                onChange={(event) => setChangeReason(event.target.value)}
                placeholder="Кратко, без персональных данных"
              />
            </label>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className="rounded border border-line px-4 py-2 min-h-tap"
                onClick={closeChangeModal}
              >
                Отмена
              </button>
              <button
                type="button"
                className="rounded bg-accent px-4 py-2 text-on-accent min-h-tap"
                disabled={
                  !changeReason.trim() ||
                  !effectiveFromMonth ||
                  createVersion.isPending ||
                  readOnly
                }
                onClick={() => createVersion.mutate()}
              >
                {createVersion.isPending ? "Создаём…" : "Создать версию"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </Shell>
  );
}
