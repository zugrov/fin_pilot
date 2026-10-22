export type ApplyCursor = {
  business_date: string;
  transaction_id: string;
};

export type ApplyCounters = {
  applied: number;
  skipped_locked: number;
  skipped_categorized: number;
  skipped_higher_priority: number;
  total_matches: number;
};

export type ApplyPageResult = ApplyCounters & {
  has_more: boolean;
  cursor: ApplyCursor | null;
};

export function emptyApplyCounters(): ApplyCounters {
  return {
    applied: 0,
    skipped_locked: 0,
    skipped_categorized: 0,
    skipped_higher_priority: 0,
    total_matches: 0,
  };
}

export function mergeApplyCounters(into: ApplyCounters, page: ApplyCounters): ApplyCounters {
  return {
    applied: into.applied + page.applied,
    skipped_locked: into.skipped_locked + page.skipped_locked,
    skipped_categorized: into.skipped_categorized + page.skipped_categorized,
    skipped_higher_priority: into.skipped_higher_priority + page.skipped_higher_priority,
    total_matches: into.total_matches + page.total_matches,
  };
}

/** Последовательное применение правила по cursor до has_more=false. */
export async function applyRuleUntilDone(
  fetchPage: (cursor: ApplyCursor | null) => Promise<ApplyPageResult>,
  onPage?: (totals: ApplyCounters, page: ApplyPageResult) => void,
): Promise<ApplyCounters> {
  let totals = emptyApplyCounters();
  let cursor: ApplyCursor | null = null;
  for (;;) {
    const page = await fetchPage(cursor);
    totals = mergeApplyCounters(totals, page);
    onPage?.(totals, page);
    if (!page.has_more) {
      return totals;
    }
    if (!page.cursor) {
      throw new Error("Сервер не вернул курсор продолжения");
    }
    cursor = page.cursor;
  }
}
