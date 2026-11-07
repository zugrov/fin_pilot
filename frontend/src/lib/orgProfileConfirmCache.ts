/** Обновлять кэш GET профиля текущего месяца после confirm, если версия уже действует в этом периоде. */
export function shouldPatchCurrentPeriodProfileCache(
  effectiveFrom: string,
  currentPeriod: string,
): boolean {
  return effectiveFrom <= currentPeriod;
}
