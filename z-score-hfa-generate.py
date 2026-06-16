#!/usr/bin/env python3
"""
Generates a DHIS2 program rule expression for uncapped HFA z-scores for OTP:

    python3 z-score-hfa-generate.py > z-score-hfa-formula-otp.txt

The generated expression assumes these program rule variables:

    A{var_age_in_months_otp}  Date of Birth TEI attribute
    #{var_height_otp}         height in cm
    A{var_sex_otp}            option code: 0 = Male, 1 = Female

Program rule condition for the ASSIGN action using this expression:

    d2:hasValue(A{var_age_in_months_otp}) &&
    d2:hasValue(#{var_height_otp}) &&
    d2:hasValue(A{var_sex_otp}) &&
    d2:monthsBetween(A{var_age_in_months_otp}, V{event_date}) >= 0 &&
    d2:monthsBetween(A{var_age_in_months_otp}, V{event_date}) <= 60
"""

import re
from dataclasses import dataclass
from urllib.request import urlopen


DOB = "A{var_age_in_months_otp}"
EVENT_DATE = "V{event_date}"
AGE_MONTHS = f"d2:monthsBetween({DOB}, {EVENT_DATE})"
HEIGHT = "#{var_height_otp}"
GENDER = "A{var_sex_otp}"

# Sources:
# - Z-score logic:
#   https://github.com/dhis2/expression-parser/blob/v1.4.2/src/commonMain/kotlin/org/hisp/dhis/lib/expression/math/ZScore.kt#L21-L68
# - HFA table source:
ZSCORE_TABLE_URL = "https://github.com/dhis2/expression-parser/blob/v1.4.2/src/commonMain/kotlin/org/hisp/dhis/lib/expression/math/ZScoreTable.kt"

ADD_ENTRY_RE = re.compile(
    r"addEntry\(res,\s*(?P<sex>[01]),\s*(?P<age>[0-9.]+),\s*"
    r"newSDMap\((?P<values>[^)]*)\)\)"
)

@dataclass(frozen=True)
class Row:
    age: float
    sd3neg: float
    sd2neg: float
    sd1neg: float
    sd0: float
    sd1: float
    sd2: float
    sd3: float

def fetch_table_source(blob_url: str = ZSCORE_TABLE_URL) -> str:
    raw = blob_url.replace(
        "https://github.com/",
        "https://raw.githubusercontent.com/",
        1,
    ).replace("/blob/", "/", 1)
    return urlopen(raw, timeout=20).read().decode("utf-8")

def parse_float(value: str) -> float:
    return float(value.strip().removesuffix("f"))

def parse_table(source: str, function_name: str) -> list[Row]:
    rows: list[Row] = []
    lines = iter(source.splitlines())

    for line in lines:
        if f"fun {function_name}(" in line:
            break

    for line in lines:
        if "return res.toMap()" in line:
            break
        if match := ADD_ENTRY_RE.search(line):
            values = map(parse_float, match["values"].split(","))
            rows.append(Row(parse_float(match["age"]), *values))

    return rows

def n(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.12g}"

def ge(left: str, right: str) -> str:
    return f"d2:oizp(({left}) - ({right}))"

def le(left: str, right: str) -> str:
    return f"d2:oizp(({right}) - ({left}))"

def eq(left: str, right: str) -> str:
    return f"({ge(left, right)} * {le(left, right)})"

def lt(left: str, right: str) -> str:
    return f"(1 - {ge(left, right)})"

def gt(left: str, right: str) -> str:
    return f"(1 - {le(left, right)})"

def row_correction_expr(row: Row) -> str:
    low_distance = row.sd2neg - row.sd3neg
    high_distance = row.sd3 - row.sd2
    low_threshold = row.sd3neg - low_distance / 2
    high_threshold = row.sd3 + high_distance / 2
    low = n(low_threshold)
    high = n(high_threshold)
    low_delta = f"d2:ceil((({HEIGHT} - {low}) / {n(low_distance)}) * 100) / 100"
    high_delta = f"d2:floor((({HEIGHT} - {high}) / {n(high_distance)}) * 100) / 100"

    return (
        f"({eq(AGE_MONTHS, n(row.age))} * ("
        f"({lt(HEIGHT, low)} * ({low_delta})) + "
        f"({gt(HEIGHT, high)} * ({high_delta}))"
        f"))"
    )

def table_correction_expr(rows: list[Row]) -> str:
    return " + ".join(row_correction_expr(row) for row in rows) or "0"

def builtin_hfa(gender_literal: str) -> str:
    return f'd2:zScoreHFA({AGE_MONTHS},{HEIGHT},"{gender_literal}")'

def main() -> None:
    source = fetch_table_source()
    boys = parse_table(source, "newZScoreHFATableBoy")
    girls = parse_table(source, "newZScoreHFATableGirl")
    boy_mask = eq(GENDER, "0")
    print(
        f"({boy_mask} * ({builtin_hfa('0')} + ({table_correction_expr(boys)}))) + "
        f"((1 - {boy_mask}) * ({builtin_hfa('1')} + ({table_correction_expr(girls)})))"
    )

if __name__ == "__main__":
    main()
