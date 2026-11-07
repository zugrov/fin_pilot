export function isOrgProfileReadOnly(canWrite: boolean | undefined): boolean {
  return canWrite === false;
}
