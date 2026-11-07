"""Допустимые значения полей профиля (ADR-003 §2)."""

ORG_FORMS = frozenset({"unspecified", "ip", "ooo", "ao"})
TAX_SYSTEMS = frozenset(
    {"unspecified", "usn", "osno", "ausn", "psn", "eshn", "self_employed"}
)
USN_TAX_OBJECTS = frozenset({"unspecified", "income", "income_minus_expense"})
VAT_STATUSES = frozenset(
    {"unknown", "vat_payer", "special_rates_5_7", "exemption", "not_applicable"}
)
VAT_REGIME_DETAIL_VALUES = frozenset(
    {"unspecified", "with_deductions", "special_without_deductions"}
)
VAT_DEFAULT_RATE_VALUES = frozenset({"unspecified", "22", "10", "0"})
PRICES_INCLUDE_VAT = frozenset({"unknown", "yes", "no"})
REVENUE_RECOGNITION_METHODS = frozenset({"unknown", "accrual", "cash", "other"})
ACCOUNTING_SOURCES = frozenset({"unspecified", "onec", "cloud", "book_csv"})
INDUSTRY_SPHERES = frozenset({"unspecified", "trade", "services", "production", "mixed"})
MONEY_CHANNELS = frozenset({"unspecified", "bank", "acquiring", "cash", "other"})
PRIOR_YEAR_REVENUE_BANDS = frozenset(
    {
        "unknown",
        "unspecified",
        "under_20m",
        "from_20m_to_272_5m",
        "from_272_5m_to_490_5m",
        "over_490_5m",
    }
)
MONTH_CLOSE_POLICIES = frozenset({"unknown", "calendar_month_end", "manual", "other"})

IP_ONLY_TAX_SYSTEMS = frozenset({"psn", "self_employed"})
