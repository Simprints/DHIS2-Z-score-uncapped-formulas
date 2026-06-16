# Z-score uncapped formulas for DHIS2

Z-scores are numerical metrics of how much a pair of child's weight/height (the WFH z-score), age/height (the HFA z-score) or age/weight (the WFA z-score) deviate from statistically common values. The unit of measurement is 1 standard deviation. Low (highly negative) values may indicate malnourishment.

DHIS2 has standard implementations for z-scores, but those are coerced to the range of [-3.5, 3.5]. In some DHIS2 projects, the requirement is to remove this "cap" - to allow values beyond this range.

Because the formulas are based on tables of statistical data about children growth, it's impractical to manually type them into the program rule field in the DHIS2 instance Maintenance web UI form - the formulas are way too big. Instead, this repo contains short Python scripts which generate the formulas. For convenience, the ready formulas are in the `output` folder. There are also validation scripts in the `test` folder, for verifying that the uncapped formulas are indeed the extensions of the standard DHIS2 ones across full ranges of arguments.

There's some domain-specific terminology involved in the scripts:
* OTP: Outpatient Therapeutic Program (for severe malnutrition)
* TSFP: Targeted Supplementary Feeding Program (for moderate malnutrition)
* RAMP: Relapse to Acute Malnutrition Prevention

The scripts generate formulas for the OTP program. Formulas for TSFP or RAMP can be obtained by replacing all `_otp` substrings with `_tsfp` or `_ramp`. For convenience, this is already done in the ready formulas in the `output` folder. If you check in the scripts that the program rule variable names match, the formulas are ready to paste into the value assignment form.

References:
* Z-score logic in the DHIS2 expression parser: https://github.com/dhis2/expression-parser/blob/v1.4.2/src/commonMain/kotlin/org/hisp/dhis/lib/expression/math/ZScore.kt#L21-L68
* Z-score statistical data tables in the DHIS2 expression parser: https://github.com/dhis2/expression-parser/blob/v1.4.2/src/commonMain/kotlin/org/hisp/dhis/lib/expression/math/ZScoreTable.kt
* DHIS2 program rules configuration documentation: https://github.com/dhis2/training-docs/blob/main/content/tracker_config/tg_programrules.md#create-the-program-rule
