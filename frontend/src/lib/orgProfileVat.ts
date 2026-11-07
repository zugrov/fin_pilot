export type VatQuestionId =
  | "general_payer"
  | "usn_special"
  | "exemption_145"
  | "not_applicable"
  | "unknown";

export type VatMapping = {
  vat_status: string;
  vat_regime_detail?: string | null;
  vat_default_rate?: string | null;
  vat_exemption_article_145?: boolean | null;
};

export function mapVatQuestionToSnapshot(
  answer: VatQuestionId,
  opts: { taxSystem: string; vatDefaultRate?: string },
): VatMapping {
  switch (answer) {
    case "general_payer":
      return {
        vat_status: "vat_payer",
        vat_regime_detail: "with_deductions",
        vat_default_rate: opts.vatDefaultRate ?? "22",
        vat_exemption_article_145: false,
      };
    case "usn_special":
      return {
        vat_status: "special_rates_5_7",
        vat_regime_detail: "special_without_deductions",
        vat_default_rate: null,
        vat_exemption_article_145: false,
      };
    case "exemption_145":
      return {
        vat_status: "exemption",
        vat_regime_detail: "unspecified",
        vat_default_rate: null,
        vat_exemption_article_145: true,
      };
    case "not_applicable":
      return {
        vat_status: "not_applicable",
        vat_regime_detail: null,
        vat_default_rate: null,
        vat_exemption_article_145: false,
      };
    default:
      return {
        vat_status: "unknown",
        vat_regime_detail: null,
        vat_default_rate: null,
        vat_exemption_article_145: null,
      };
  }
}

export function snapshotToVatQuestion(snapshot: {
  vat_status: string;
  vat_regime_detail?: string | null;
  vat_exemption_article_145?: boolean | null;
}): VatQuestionId {
  const vs = snapshot.vat_status;
  if (vs === "vat_payer") {
    return "general_payer";
  }
  if (vs === "special_rates_5_7") {
    return "usn_special";
  }
  if (vs === "exemption") {
    return "exemption_145";
  }
  if (vs === "not_applicable") {
    return "not_applicable";
  }
  return "unknown";
}

export function step3FieldVisibility(snapshot: {
  tax_system: string;
  vat_status: string;
  is_new_organization?: boolean | null;
}): {
  showUsnObject: boolean;
  showVatRate: boolean;
  showRevenueBand: boolean;
} {
  return {
    showUsnObject: snapshot.tax_system === "usn",
    showVatRate: snapshot.vat_status === "vat_payer",
    showRevenueBand: snapshot.is_new_organization !== true,
  };
}

export function buildStep3DraftPatch(args: {
  taxSystem: string;
  vatAnswer: VatQuestionId;
  vatRate: string;
  pricesIncludeVat: string;
  isNewOrg: boolean | null;
  revenueBand: string;
}): Record<string, unknown> {
  const mapped = mapVatQuestionToSnapshot(args.vatAnswer, {
    taxSystem: args.taxSystem,
    vatDefaultRate: args.vatRate,
  });
  const body: Record<string, unknown> = {
    ...mapped,
    prices_include_vat: args.pricesIncludeVat,
    is_new_organization: args.isNewOrg,
  };
  if (args.isNewOrg === true) {
    body.prior_year_revenue_band = "unknown";
  } else {
    body.prior_year_revenue_band = args.revenueBand;
  }
  return body;
}

export function showUsnExemptionThresholdHint(args: {
  taxSystem: string;
  revenueBand: string;
  vatAnswer: VatQuestionId;
}): boolean {
  return (
    args.taxSystem === "usn" &&
    args.revenueBand === "under_exemption_threshold" &&
    args.vatAnswer === "unknown"
  );
}
