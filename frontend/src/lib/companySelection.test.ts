import { describe, expect, it, vi } from "vitest";

import {
  FP_COMPANY_ID_KEY,
  type CompanyRef,
  alertsRecalcTarget,
  calendarMutationTarget,
  clearStoredCompanyIdIfInvalid,
  companyListPhase,
  companyScopedData,
  deriveWritableCompanySelection,
  guardWriteRequest,
  importUploadTarget,
  resetImportDependentState,
  resolveWritableCompany,
  salesMutationTarget,
  sanitizeStoredCompanyId,
  syncStorageAfterCompaniesLoaded,
} from "./companySelection";

const firmA = { id: "firm-a", name: "Alpha" };
const firmB = { id: "firm-b", name: "Beta" };

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => [...map.keys()][index] ?? null,
    removeItem: (key: string) => {
      map.delete(key);
    },
    setItem: (key: string, value: string) => {
      map.set(key, value);
    },
  };
}

describe("resolveWritableCompany", () => {
  it("returns null for empty list", () => {
    expect(resolveWritableCompany([], null, null)).toEqual({ companyId: null, company: null });
  });

  it("auto-selects the only company", () => {
    const ctx = resolveWritableCompany([firmA], null, null);
    expect(ctx.companyId).toBe("firm-a");
    expect(ctx.company?.name).toBe("Alpha");
  });

  it("requires explicit choice for two companies without stored id", () => {
    expect(resolveWritableCompany([firmA, firmB], null, null).companyId).toBeNull();
  });

  it("uses valid stored choice for multiple companies", () => {
    const ctx = resolveWritableCompany([firmA, firmB], "firm-b", null);
    expect(ctx.companyId).toBe("firm-b");
  });

  it("ignores unavailable stored id", () => {
    expect(resolveWritableCompany([firmA, firmB], "firm-x", null).companyId).toBeNull();
  });

  it("prefers user pick over stored id", () => {
    const ctx = resolveWritableCompany([firmA, firmB], "firm-b", "firm-a");
    expect(ctx.companyId).toBe("firm-a");
  });

  it("never falls back to companies[0] when multiple and no valid choice", () => {
    const ctx = resolveWritableCompany([firmA, firmB], "gone", null);
    expect(ctx.companyId).not.toBe("firm-a");
    expect(ctx.companyId).toBeNull();
  });
});

describe("sanitizeStoredCompanyId", () => {
  it("clears stale ids from storage", () => {
    const storage = memoryStorage();
    storage.setItem(FP_COMPANY_ID_KEY, "firm-x");
    clearStoredCompanyIdIfInvalid([firmA, firmB], storage);
    expect(storage.getItem(FP_COMPANY_ID_KEY)).toBeNull();
  });

  it("keeps valid stored id", () => {
    const storage = memoryStorage();
    storage.setItem(FP_COMPANY_ID_KEY, "firm-a");
    clearStoredCompanyIdIfInvalid([firmA, firmB], storage);
    expect(storage.getItem(FP_COMPANY_ID_KEY)).toBe("firm-a");
  });
});

describe("companyScopedData", () => {
  it("hides data when query key company differs from active", () => {
    const rows = [{ id: "1" }];
    expect(companyScopedData("firm-b", "firm-a", rows)).toBeUndefined();
  });

  it("shows data for matching company", () => {
    const rows = [{ id: "1" }];
    expect(companyScopedData("firm-a", "firm-a", rows)).toEqual(rows);
  });

  it("hides data without active company", () => {
    expect(companyScopedData(null, "firm-a", [{ id: "1" }])).toBeUndefined();
  });
});

describe("resetImportDependentState", () => {
  it("clears import-specific fields on company change", () => {
    expect(resetImportDependentState()).toEqual({
      previewId: "",
      error: "",
      mailError: "",
      mailNote: "",
    });
  });
});

describe("write request guards", () => {
  it("blocks sales write without company", () => {
    expect(salesMutationTarget(null).allowed).toBe(false);
  });

  it("allows sales write with selected company", () => {
    expect(salesMutationTarget("firm-a")).toEqual({ allowed: true, companyId: "firm-a" });
  });

  it("blocks calendar write without company", () => {
    expect(calendarMutationTarget(null).allowed).toBe(false);
  });

  it("blocks import upload without company or source", () => {
    expect(importUploadTarget(null, "src-1").allowed).toBe(false);
    expect(importUploadTarget("firm-a", undefined).allowed).toBe(false);
  });

  it("allows import upload with company and source", () => {
    expect(importUploadTarget("firm-a", "src-1")).toEqual({
      allowed: true,
      companyId: "firm-a",
      sourceId: "src-1",
    });
  });

  it("blocks alerts recalc without company", () => {
    expect(alertsRecalcTarget(null).allowed).toBe(false);
  });

  it("uses selected company id in alerts recalc", () => {
    expect(alertsRecalcTarget("firm-b").companyId).toBe("firm-b");
  });
});

describe("screen binding helpers", () => {
  it("does not call write path when guard fails", () => {
    const fn = vi.fn();
    const guard = guardWriteRequest(null);
    if (guard.allowed) {
      fn(guard.companyId);
    }
    expect(fn).not.toHaveBeenCalled();
  });

  it("passes active company to write path", () => {
    const fn = vi.fn();
    const guard = salesMutationTarget("firm-a");
    if (guard.allowed) {
      fn(guard.companyId);
    }
    expect(fn).toHaveBeenCalledWith("firm-a");
  });

  it("simulates stale list: firm B active while payload keyed for firm A", () => {
    const staleEntries = [{ id: "e1" }];
    const visible = companyScopedData("firm-b", "firm-a", staleEntries);
    expect(visible).toBeUndefined();
  });

  it("sanitize drops unknown preferred id before resolve", () => {
    expect(sanitizeStoredCompanyId("firm-z", [firmA, firmB])).toBeNull();
  });
});

function simulateSelectionLifecycle(
  steps: Array<{ isSuccess: boolean; isError: boolean; companies?: CompanyRef[] }>,
  storage: Storage,
) {
  let userPickId: string | null = null;
  const snapshots: Array<{
    storageId: string | null;
    companyId: string | null;
    canWrite: boolean;
    listPhase: string;
    selectValue: string;
  }> = [];

  for (const step of steps) {
    const query = {
      isSuccess: step.isSuccess,
      isError: step.isError,
      data: step.companies !== undefined ? { companies: step.companies } : undefined,
    };
    const phase = companyListPhase(query);
    const loaded = step.isSuccess ? (step.companies ?? []) : [];
    if (phase === "ready" || phase === "empty") {
      syncStorageAfterCompaniesLoaded(loaded, storage);
    }
    const derived = deriveWritableCompanySelection(phase, loaded, userPickId, storage);
    snapshots.push({
      storageId: storage.getItem(FP_COMPANY_ID_KEY),
      companyId: derived.companyId,
      canWrite: derived.canWrite,
      listPhase: derived.listPhase,
      selectValue: derived.selectValue,
    });
  }
  return snapshots;
}

describe("company list load phases", () => {
  it("keeps storage B while list is still loading", () => {
    const storage = memoryStorage();
    storage.setItem(FP_COMPANY_ID_KEY, "firm-b");
    const query = { isSuccess: false, isError: false, data: undefined };
    expect(companyListPhase(query)).toBe("loading");
    const derived = deriveWritableCompanySelection("loading", [], null, storage);
    expect(storage.getItem(FP_COMPANY_ID_KEY)).toBe("firm-b");
    expect(derived.companyId).toBeNull();
    expect(derived.canWrite).toBe(false);
  });

  it("restores B after loading then [A, B]", () => {
    const storage = memoryStorage();
    storage.setItem(FP_COMPANY_ID_KEY, "firm-b");
    const steps = simulateSelectionLifecycle(
      [
        { isSuccess: false, isError: false },
        { isSuccess: true, isError: false, companies: [firmA, firmB] },
      ],
      storage,
    );
    expect(steps[0].storageId).toBe("firm-b");
    expect(steps[0].companyId).toBeNull();
    expect(steps[0].canWrite).toBe(false);
    expect(steps[1].storageId).toBe("firm-b");
    expect(steps[1].companyId).toBe("firm-b");
    expect(steps[1].canWrite).toBe(true);
    expect(steps[1].selectValue).toBe("firm-b");
  });

  it("clears storage when success returns empty list", () => {
    const storage = memoryStorage();
    storage.setItem(FP_COMPANY_ID_KEY, "firm-b");
    const steps = simulateSelectionLifecycle(
      [
        { isSuccess: false, isError: false },
        { isSuccess: true, isError: false, companies: [] },
      ],
      storage,
    );
    expect(steps[1].storageId).toBeNull();
    expect(steps[1].listPhase).toBe("empty");
    expect(steps[1].companyId).toBeNull();
  });

  it("drops stale B and auto-selects sole A", () => {
    const storage = memoryStorage();
    storage.setItem(FP_COMPANY_ID_KEY, "firm-b");
    const steps = simulateSelectionLifecycle(
      [{ isSuccess: true, isError: false, companies: [firmA] }],
      storage,
    );
    expect(steps[0].storageId).toBe("firm-a");
    expect(steps[0].companyId).toBe("firm-a");
    expect(steps[0].selectValue).toBe("firm-a");
    expect(steps[0].canWrite).toBe(true);
  });

  it("does not clear storage on load error", () => {
    const storage = memoryStorage();
    storage.setItem(FP_COMPANY_ID_KEY, "firm-b");
    const query = { isSuccess: false, isError: true, data: undefined };
    expect(companyListPhase(query)).toBe("error");
    const derived = deriveWritableCompanySelection("error", [], null, storage);
    expect(storage.getItem(FP_COMPANY_ID_KEY)).toBe("firm-b");
    expect(derived.canWrite).toBe(false);
    expect(derived.companyId).toBeNull();
  });

  it("treats undefined companies on success as empty, not loading", () => {
    const storage = memoryStorage();
    storage.setItem(FP_COMPANY_ID_KEY, "firm-b");
    const query = { isSuccess: true, isError: false, data: undefined };
    expect(companyListPhase(query)).toBe("empty");
    syncStorageAfterCompaniesLoaded([], storage);
    expect(storage.getItem(FP_COMPANY_ID_KEY)).toBeNull();
  });
});
