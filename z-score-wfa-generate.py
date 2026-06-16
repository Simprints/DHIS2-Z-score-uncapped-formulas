#!/usr/bin/env python3
"""
Generates a DHIS2 program rule expression for uncapped WFA z-scores for OTP:

    python3 z-score-wfa-generate.py > z-score-wfa-formula-otp.txt

The generated expression assumes these program rule variables:

    A{var_age_in_months_otp}  Date of Birth TEI attribute
    #{var_weight_otp}         weight in kg
    A{var_sex_otp}            option code: 0 = Male, 1 = Female

Program rule condition for the ASSIGN action using this expression:

    d2:hasValue(A{var_age_in_months_otp}) &&
    d2:hasValue(#{var_weight_otp}) &&
    d2:hasValue(A{var_sex_otp}) &&
    d2:monthsBetween(A{var_age_in_months_otp}, V{event_date}) >= 0 &&
    d2:monthsBetween(A{var_age_in_months_otp}, V{event_date}) <= 60

The v1.4.2 WFA boy table skips age 28. The formula provides an approximation for
boy age 28, while using the built-in plus uncapped-tail corrections elsewhere.
"""

import math
import re
from dataclasses import astuple, dataclass
from urllib.request import urlopen


DOB = "A{var_age_in_months_otp}"
EVENT_DATE = "V{event_date}"
AGE_MONTHS = f"d2:monthsBetween({DOB}, {EVENT_DATE})"
WEIGHT = "#{var_weight_otp}"
GENDER = "A{var_sex_otp}"

# Sources:
# - Z-score logic:
#   https://github.com/dhis2/expression-parser/blob/v1.4.2/src/commonMain/kotlin/org/hisp/dhis/lib/expression/math/ZScore.kt#L21-L68
# - WFA table source:
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

def complete_rows(rows: list[Row]) -> list[Row]:
    by_age = {int(row.age): row for row in rows}
    for age in sorted(set(range(61)) - set(by_age)):
        prev = by_age[age - 1]
        next_ = by_age[age + 1]
        values = [math.trunc(((a + b) / 2) * 10) / 10 for a, b in zip(astuple(prev)[1:], astuple(next_)[1:])]
        by_age[age] = Row(float(age), *values)
    return [by_age[age] for age in range(61)]

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

def trunc_pos(raw: str) -> str:
    return f"(d2:floor(({raw}) * 100) / 100)"

def trunc_neg(raw: str) -> str:
    return f"(0 - {trunc_pos(raw)})"

def interval(left: float, right: float) -> str:
    return f"({gt(WEIGHT, n(left))} * {lt(WEIGHT, n(right))})"

def row_tail_correction_expr(row: Row) -> str:
    low_distance = row.sd2neg - row.sd3neg
    high_distance = row.sd3 - row.sd2
    low_threshold = row.sd3neg - low_distance / 2
    high_threshold = row.sd3 + high_distance / 2
    low = n(low_threshold)
    high = n(high_threshold)
    low_delta = f"d2:ceil((({WEIGHT} - {low}) / {n(low_distance)}) * 100) / 100"
    high_delta = f"d2:floor((({WEIGHT} - {high}) / {n(high_distance)}) * 100) / 100"

    return (
        f"({eq(AGE_MONTHS, n(row.age))} * ("
        f"({lt(WEIGHT, low)} * ({low_delta})) + "
        f"({gt(WEIGHT, high)} * ({high_delta}))"
        f"))"
    )

def tail_corrections(rows: list[Row]) -> str:
    return " + ".join(row_tail_correction_expr(row) for row in rows) or "0"

def row_score_expr(row: Row) -> str:
    low_distance = row.sd2neg - row.sd3neg
    high_distance = row.sd3 - row.sd2
    low_threshold = row.sd3neg - low_distance / 2
    high_threshold = row.sd3 + high_distance / 2
    low_delta = f"d2:ceil((({WEIGHT} - {n(low_threshold)}) / {n(low_distance)}) * 100) / 100"
    high_delta = f"d2:floor((({WEIGHT} - {n(high_threshold)}) / {n(high_distance)}) * 100) / 100"
    parts = [
        f"({lt(WEIGHT, n(low_threshold))} * ((-3.5) + ({low_delta})))",
        f"({ge(WEIGHT, n(low_threshold))} * {lt(WEIGHT, n(row.sd3neg))} * (-3.5))",
    ]

    for value, score in [
        (row.sd3neg, -3),
        (row.sd2neg, -2),
        (row.sd1neg, -1),
        (row.sd1, 1),
        (row.sd2, 2),
        (row.sd3, 3),
    ]:
        parts.append(f"({eq(WEIGHT, n(value))} * {score})")

    for left, right, higher_sd in [
        (row.sd3neg, row.sd2neg, 2),
        (row.sd2neg, row.sd1neg, 1),
        (row.sd1neg, row.sd0, 0),
    ]:
        raw = f"{higher_sd} + (({n(right)} - {WEIGHT}) / {n(right - left)})"
        parts.append(f"({interval(left, right)} * {trunc_neg(raw)})")

    for left, right, lower_sd in [
        (row.sd0, row.sd1, 0),
        (row.sd1, row.sd2, 1),
        (row.sd2, row.sd3, 2),
    ]:
        raw = f"{lower_sd} + (({WEIGHT} - {n(left)}) / {n(right - left)})"
        parts.append(f"({interval(left, right)} * {trunc_pos(raw)})")

    parts += [
        f"({gt(WEIGHT, n(row.sd3))} * {le(WEIGHT, n(high_threshold))} * 3.5)",
        f"({gt(WEIGHT, n(high_threshold))} * (3.5 + ({high_delta})))",
    ]
    return " + ".join(parts)

def builtin_wfa(age_expr: str, gender_literal: str) -> str:
    return f'd2:zScoreWFA({age_expr},{WEIGHT},"{gender_literal}")'

def main() -> None:
    source = fetch_table_source()
    boy_rows = parse_table(source, "newZScoreWFATableBoy")
    girl_rows = parse_table(source, "newZScoreWFATableGirl")
    boy_28 = complete_rows(boy_rows)[28]
    age_28 = eq(AGE_MONTHS, "28")
    safe_boy_age = f"({AGE_MONTHS} + {age_28})"
    boy_mask = eq(GENDER, "0")
    boy_non_28 = f"{builtin_wfa(safe_boy_age, '0')} + ({tail_corrections([r for r in boy_rows if r.age != 28])})"
    boy_expr = f"((1 - {age_28}) * ({boy_non_28})) + ({age_28} * ({row_score_expr(boy_28)}))"
    girl_expr = f"{builtin_wfa(AGE_MONTHS, '1')} + ({tail_corrections(girl_rows)})"
    print(f"({boy_mask} * ({boy_expr})) + ((1 - {boy_mask}) * ({girl_expr}))")

if __name__ == "__main__":
    main()
