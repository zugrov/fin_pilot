export type Features = { classification_packs: boolean };

/** Флаги приходят с сервера; здесь только безопасное значение по умолчанию. */
export const DEFAULT_FEATURES: Features = { classification_packs: false };

export function normalizeFeatures(raw: Partial<Features> | undefined): Features {
  return { classification_packs: raw?.classification_packs === true };
}

export function isPacksEnabled(features: Features): boolean {
  return features.classification_packs;
}
