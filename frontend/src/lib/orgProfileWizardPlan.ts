import { companyDate } from "./forecast";

export function currentPeriodMonth(timeZone: string, now = new Date()): string {
  const local = companyDate(timeZone, now);
  return `${local.slice(0, 7)}-01`;
}

export function maxPeriodMonth(a: string, b: string): string {
  return a >= b ? a : b;
}

/** Период GET профиля для мастера: max(текущий месяц, effective_from последней версии). */
export function wizardProfilePeriod(
  timeZone: string,
  latestEffectiveFrom: string | undefined,
  now = new Date(),
): string {
  const current = currentPeriodMonth(timeZone, now);
  if (!latestEffectiveFrom) {
    return current;
  }
  return maxPeriodMonth(current, latestEffectiveFrom);
}

export type ProfileVersionRow = {
  version_id: string;
  effective_from: string;
  is_confirmed: boolean;
};

export function latestProfileVersion<T extends ProfileVersionRow>(
  versions: T[] | undefined,
): T | undefined {
  if (!versions?.length) {
    return undefined;
  }
  return versions[versions.length - 1];
}

export function step6FieldsMatchSaved(
  monthClosePolicy: string,
  revenueRecognition: string,
  profile: { month_close_policy: string; revenue_recognition_method: string } | undefined,
): boolean {
  if (!profile) {
    return false;
  }
  return (
    monthClosePolicy === profile.month_close_policy &&
    revenueRecognition === profile.revenue_recognition_method
  );
}

export function canConfirmOrganizationProfile(
  profile:
    | {
        confirm_readiness: { ready: boolean };
        month_close_policy: string;
        revenue_recognition_method: string;
      }
    | undefined,
  monthClosePolicy: string,
  revenueRecognition: string,
): boolean {
  if (!profile?.confirm_readiness.ready) {
    return false;
  }
  return step6FieldsMatchSaved(monthClosePolicy, revenueRecognition, profile);
}

export function shouldShowWizard(latest: ProfileVersionRow | undefined): boolean {
  if (!latest) {
    return true;
  }
  return !latest.is_confirmed;
}

export function isFutureUnconfirmedDraft(
  latest: ProfileVersionRow | undefined,
  currentPeriod: string,
): boolean {
  if (!latest || latest.is_confirmed) {
    return false;
  }
  return latest.effective_from > currentPeriod;
}

export function confirmTargetVersionId(
  latest: ProfileVersionRow | undefined,
  profileVersionId: string | undefined,
): string | undefined {
  return latest?.version_id ?? profileVersionId;
}

export function maxYearMonth(a: string, b: string): string {
  return a >= b ? a : b;
}

export function wizardWriteActionsVisible(canWrite: boolean | undefined): boolean {
  return canWrite !== false;
}
