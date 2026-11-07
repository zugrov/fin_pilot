import type { OrganizationProfile } from "../api";

import type { ProfileVersionRow } from "./orgProfileWizardPlan";

/** Источник снимка для POST versions: последняя (wizard) версия, иначе карточка. */
export function versionCreateSnapshotSource(
  wizardProfile: OrganizationProfile | undefined,
  cardProfile: OrganizationProfile | undefined,
): OrganizationProfile | undefined {
  return wizardProfile ?? cardProfile;
}

/** Подтверждённая версия с effective_from позже текущего периода. */
export function confirmedFutureVersion(
  versions: ProfileVersionRow[] | undefined,
  currentPeriod: string,
): ProfileVersionRow | undefined {
  if (!versions?.length) {
    return undefined;
  }
  return [...versions]
    .reverse()
    .find((row) => row.is_confirmed && row.effective_from > currentPeriod);
}
