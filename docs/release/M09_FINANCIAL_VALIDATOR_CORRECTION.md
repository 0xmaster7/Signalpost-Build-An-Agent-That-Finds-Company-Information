# M09 historical financial validator correction

The 2026-10-05 live smoke report recorded 1,875 financial metric claims and zero unsupported publications. That run's smoke validator checked currency, period, scope, and numeric value but did not require a source unit. Its historical zero therefore does not establish that all 1,875 claims had complete scale semantics. The raw output and state bundle were retained only under `/private/tmp` and are no longer available for unit-aware revalidation.

The Sol-audit remediation requires an explicit supported unit on every canonical financial metric, inherits a record-level BRREG unit only when a metric-level unit is absent, and withholds a metric when the unit is missing or unsupported. It does not convert TNOK/MNOK to NOK. Future smoke reports must use the corrected validator. The 2026-10-05 measurements remain historical measurements and are not rewritten.
