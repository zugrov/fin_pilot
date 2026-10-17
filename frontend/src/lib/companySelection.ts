import { useCallback, useEffect, useRef, useState } from "react";

export const FP_COMPANY_ID_KEY = "fp_company_id";

export type CompanyRef = {
  id: string;
  name: string;
  status?: string;
  timezone?: string;
};

export type WritableCompanyContext = {
  companyId: string | null;
  company: CompanyRef | null;
};

/** Список firm с сервера: ещё не получен / пустой успешный ответ / есть firm. */
export type CompanyListPhase = "loading" | "empty" | "ready";

export type CompaniesQuerySlice = {
  data?: { companies?: CompanyRef[] };
  isSuccess: boolean;
  isError: boolean;
};

export type ImportDependentState = {
  previewId: string;
  error: string;
  mailError: string;
  mailNote: string;
};

export function readStoredCompanyId(storage: Storage = sessionStorage): string | null {
  return storage.getItem(FP_COMPANY_ID_KEY);
}

export function sanitizeStoredCompanyId(
  stored: string | null,
  companies: readonly CompanyRef[],
): string | null {
  if (!stored) {
    return null;
  }
  return companies.some((item) => item.id === stored) ? stored : null;
}

export function clearStoredCompanyIdIfInvalid(
  companies: readonly CompanyRef[],
  storage: Storage = sessionStorage,
): void {
  const stored = storage.getItem(FP_COMPANY_ID_KEY);
  if (stored && !sanitizeStoredCompanyId(stored, companies)) {
    storage.removeItem(FP_COMPANY_ID_KEY);
  }
}

/** После успешной загрузки списка: убрать устаревший ID, автосохранить единственную firm. */
export function syncStorageAfterCompaniesLoaded(
  companies: readonly CompanyRef[],
  storage: Storage = sessionStorage,
): void {
  clearStoredCompanyIdIfInvalid(companies, storage);
  if (companies.length === 1) {
    persistCompanyChoice(companies[0].id, companies, storage);
  }
}

export function companyListPhase(query: CompaniesQuerySlice): CompanyListPhase | "error" {
  if (query.isError) {
    return "error";
  }
  if (!query.isSuccess) {
    return "loading";
  }
  const list = query.data?.companies ?? [];
  return list.length === 0 ? "empty" : "ready";
}

export function loadedCompaniesFromQuery(query: CompaniesQuerySlice): CompanyRef[] {
  if (!query.isSuccess) {
    return [];
  }
  return query.data?.companies ?? [];
}

/** Выбор фирмы для записывающих экранов: без silent companies[0] при нескольких firm. */
export function resolveWritableCompany(
  companies: readonly CompanyRef[],
  storedId: string | null,
  userPickId: string | null,
): WritableCompanyContext {
  if (companies.length === 0) {
    return { companyId: null, company: null };
  }
  if (companies.length === 1) {
    return { companyId: companies[0].id, company: companies[0] };
  }
  const validStored = sanitizeStoredCompanyId(storedId, companies);
  const validPick =
    userPickId && companies.some((item) => item.id === userPickId) ? userPickId : null;
  const chosen = validPick ?? validStored ?? null;
  const company = chosen ? (companies.find((item) => item.id === chosen) ?? null) : null;
  return { companyId: chosen, company };
}

export type DerivedWritableSelection = WritableCompanyContext & {
  listPhase: CompanyListPhase | "error";
  list: CompanyRef[];
  canWrite: boolean;
  selectValue: string;
  needsPlaceholder: boolean;
};

export function deriveWritableCompanySelection(
  listPhase: CompanyListPhase | "error",
  companies: readonly CompanyRef[],
  userPickId: string | null,
  storage: Storage = sessionStorage,
): DerivedWritableSelection {
  if (listPhase === "loading" || listPhase === "error") {
    return {
      companyId: null,
      company: null,
      listPhase,
      list: [],
      canWrite: false,
      selectValue: "",
      needsPlaceholder: false,
    };
  }
  if (listPhase === "empty") {
    return {
      companyId: null,
      company: null,
      listPhase: "empty",
      list: [],
      canWrite: false,
      selectValue: "",
      needsPlaceholder: false,
    };
  }
  const stored = readStoredCompanyId(storage);
  const resolved = resolveWritableCompany(companies, stored, userPickId);
  return {
    ...resolved,
    listPhase: "ready",
    list: [...companies],
    canWrite: Boolean(resolved.companyId),
    selectValue: resolved.companyId ?? "",
    needsPlaceholder: companyPickerNeedsPlaceholder(companies),
  };
}

export function canWriteWithCompany(companyId: string | null): boolean {
  return Boolean(companyId);
}

export function companyPickerNeedsPlaceholder(companies: readonly CompanyRef[]): boolean {
  return companies.length > 1;
}

export function persistCompanyChoice(
  companyId: string,
  companies: readonly CompanyRef[],
  storage: Storage = sessionStorage,
): void {
  if (companies.some((item) => item.id === companyId)) {
    storage.setItem(FP_COMPANY_ID_KEY, companyId);
  }
}

export function clearPersistedCompanyChoice(storage: Storage = sessionStorage): void {
  storage.removeItem(FP_COMPANY_ID_KEY);
}

/** Не показывать кэш списка, если ключ запроса не совпадает с активной firm. */
export function companyScopedData<T>(
  activeCompanyId: string | null,
  queryKeyCompanyId: string | undefined,
  data: T | undefined,
): T | undefined {
  if (!activeCompanyId || queryKeyCompanyId !== activeCompanyId) {
    return undefined;
  }
  return data;
}

export function resetImportDependentState(): ImportDependentState {
  return {
    previewId: "",
    error: "",
    mailError: "",
    mailNote: "",
  };
}

export type WriteRequestGuard = {
  allowed: boolean;
  companyId: string;
};

export function guardWriteRequest(companyId: string | null): WriteRequestGuard {
  if (!companyId) {
    return { allowed: false, companyId: "" };
  }
  return { allowed: true, companyId };
}

export function salesMutationTarget(companyId: string | null): WriteRequestGuard {
  return guardWriteRequest(companyId);
}

export function calendarMutationTarget(companyId: string | null): WriteRequestGuard {
  return guardWriteRequest(companyId);
}

export function importUploadTarget(
  companyId: string | null,
  sourceId: string | undefined,
): { allowed: boolean; companyId: string; sourceId: string } {
  const base = guardWriteRequest(companyId);
  if (!base.allowed || !sourceId) {
    return { allowed: false, companyId: "", sourceId: "" };
  }
  return { allowed: true, companyId: base.companyId, sourceId };
}

export function alertsRecalcTarget(companyId: string | null): WriteRequestGuard {
  return guardWriteRequest(companyId);
}

type UseWritableCompanyOptions = {
  writePending?: boolean;
  onCompanyChanged?: (prevId: string | null, nextId: string | null) => void;
  storage?: Storage;
};

export function useWritableCompanySelection(
  query: CompaniesQuerySlice,
  options: UseWritableCompanyOptions = {},
) {
  const { writePending = false, onCompanyChanged, storage = sessionStorage } = options;
  const [userPickId, setUserPickId] = useState<string | null>(null);
  const prevCompanyId = useRef<string | null>(null);
  const phase = companyListPhase(query);
  const loadedList = loadedCompaniesFromQuery(query);

  useEffect(() => {
    if (phase === "ready" || phase === "empty") {
      syncStorageAfterCompaniesLoaded(loadedList, storage);
    }
  }, [phase, loadedList, storage]);

  const derived = deriveWritableCompanySelection(phase, loadedList, userPickId, storage);
  const { companyId, company, list, listPhase, canWrite, selectValue, needsPlaceholder } = derived;

  useEffect(() => {
    if (prevCompanyId.current !== companyId) {
      onCompanyChanged?.(prevCompanyId.current, companyId);
      prevCompanyId.current = companyId;
    }
  }, [companyId, onCompanyChanged]);

  const onSelect = useCallback(
    (nextRaw: string) => {
      if (writePending || listPhase !== "ready") {
        return;
      }
      if (!nextRaw) {
        setUserPickId("");
        clearPersistedCompanyChoice(storage);
        return;
      }
      if (list.some((item) => item.id === nextRaw)) {
        setUserPickId(nextRaw);
        persistCompanyChoice(nextRaw, list, storage);
      }
    },
    [list, listPhase, storage, writePending],
  );

  return {
    list,
    listPhase,
    companyId,
    company,
    selectValue,
    onSelect,
    canWrite,
    pickerDisabled: writePending || listPhase !== "ready",
    needsPlaceholder,
  };
}
