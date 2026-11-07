import { WalletRequestError } from "../api";

export function fieldErrorsFromUnknown(exc: unknown): Record<string, string[]> {
  if (exc instanceof WalletRequestError && exc.fieldErrors) {
    return exc.fieldErrors;
  }
  return {};
}

export function mergeFieldErrorTexts(
  fieldErrors: Record<string, string[]>,
  messageFor: (field: string, code: string) => string,
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [field, codes] of Object.entries(fieldErrors)) {
    out[field] = codes.map((code) => messageFor(field, code));
  }
  return out;
}
