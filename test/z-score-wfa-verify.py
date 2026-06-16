#!/usr/bin/env python3
"""
Verifies a generated uncapped WFA z-score formula for OTP.

Usage:

    python3 z-score-wfa-verify.py z-score-wfa-formula-otp.txt

The verifier checks the generated formula over:

    genders: 0, 1
    ages: 0..60 months, 1 month step
    weights: 0.1..40.0 kg, 0.1 kg step

It compares the generated formula with a table-based WFA
reference. The v1.4.2 WFA boy table skips age 28, so reference fills only
that one-row gap from ages 27 and 29.
"""

import math
from datetime import date
import re
import sys
from collections import namedtuple
from pathlib import Path
from urllib.request import urlopen

AGES = list(range(0, 61))
WEIGHTS = range(1, 401)
CAP = 3.5
TOL = 1e-9
EVENT_DATE = date(2026, 6, 16)
TABLE_URL = "https://github.com/dhis2/expression-parser/blob/v1.4.2/src/commonMain/kotlin/org/hisp/dhis/lib/expression/math/ZScoreTable.kt"
ROW_RE = re.compile(
    r"addEntry\(res,\s*(?P<sex>[01]),\s*(?P<age>[0-9.]+),\s*"
    r"newSDMap\((?P<values>[^)]*)\)\)"
)
Row = namedtuple("Row", "age sd3neg sd2neg sd1neg sd0 sd1 sd2 sd3")

def num(value):
    return float(value.strip().removesuffix("f"))

def fetch_tables():
    raw_url = TABLE_URL.replace(
        "https://github.com/",
        "https://raw.githubusercontent.com/",
        1,
    ).replace("/blob/", "/", 1)
    source = urlopen(raw_url, timeout=20).read().decode("utf-8")
    raw = {
        "m": parse_table(source, "newZScoreWFATableBoy", "0"),
        "f": parse_table(source, "newZScoreWFATableGirl", "1"),
    }
    complete = {
        "m": complete_table(dict(raw["m"]), "boy"),
        "f": complete_table(dict(raw["f"]), "girl"),
    }
    return raw, complete

def parse_table(source, function_name, expected_sex):
    rows = {}
    sexes = set()
    lines = iter(source.splitlines())

    for line in lines:
        if f"fun {function_name}(" in line:
            break

    for line in lines:
        if "return res.toMap()" in line:
            break
        if match := ROW_RE.search(line):
            sexes.add(match["sex"])
            values = [num(match["age"])] + [num(value) for value in match["values"].split(",")]
            row = Row(*values)
            rows[int(row.age)] = row

    assert sexes == {expected_sex}, f"{function_name}: unexpected WFA table sex"
    return rows

def complete_table(rows, label):
    missing = sorted(set(range(61)) - set(rows))
    assert not missing or missing == [28] and label == "boy", (
        f"unexpected missing {label} WFA ages: {missing}"
    )
    for age in missing:
        prev = rows[age - 1]
        next_ = rows[age + 1]
        values = [math.trunc(((a + b) / 2) * 10) / 10 for a, b in zip(prev[1:], next_[1:])]
        rows[age] = Row(float(age), *values)
    return rows

RAW_TABLES, TABLES = fetch_tables()

def gender_key(gender):
    if isinstance(gender, bool):
        gender = str(gender).lower()
    elif isinstance(gender, (int, float)) and float(gender).is_integer():
        gender = str(int(gender))
    return "m" if str(gender) in {"male", "MALE", "Male", "ma", "m", "M", "0", "false"} else "f"

def n(value):
    return str(int(value)) if value.is_integer() else f"{value:.12g}"

def q(value):
    return float(n(value))

def trunc2(value):
    return math.trunc(value * 100) / 100

def capped_wfa(age, weight, gender, tables=TABLES):
    row = tables[gender_key(gender)][int(math.floor(age))]
    for key, score in [
        (q(row.sd3neg), -3),
        (q(row.sd2neg), -2),
        (q(row.sd1neg), -1),
        (q(row.sd0), 0),
        (q(row.sd1), 1),
        (q(row.sd2), 2),
        (q(row.sd3), 3),
    ]:
        if abs(weight - key) < TOL:
            return float(score)
    if weight > q(row.sd3):
        return CAP
    if weight < q(row.sd3neg):
        return -CAP

    for left, right, higher_sd in [
        (row.sd3neg, row.sd2neg, 2),
        (row.sd2neg, row.sd1neg, 1),
        (row.sd1neg, row.sd0, 0),
    ]:
        left, right, distance = q(left), q(right), q(right - left)
        if left < weight < right:
            return -trunc2(higher_sd + (right - weight) / distance)

    for left, right, lower_sd in [
        (row.sd0, row.sd1, 0),
        (row.sd1, row.sd2, 1),
        (row.sd2, row.sd3, 2),
    ]:
        left, right, distance = q(left), q(right), q(right - left)
        if left < weight < right:
            return trunc2(lower_sd + (weight - left) / distance)

    return 0.0

def expected_wfa(age, weight, gender):
    row = TABLES[gender_key(gender)][int(math.floor(age))]
    low_distance = q(row.sd2neg - row.sd3neg)
    high_distance = q(row.sd3 - row.sd2)
    low_threshold = q(row.sd3neg - (row.sd2neg - row.sd3neg) / 2)
    high_threshold = q(row.sd3 + (row.sd3 - row.sd2) / 2)

    if weight < low_threshold:
        return -CAP + math.ceil(((weight - low_threshold) / low_distance) * 100) / 100
    if weight > high_threshold:
        return CAP + math.floor(((weight - high_threshold) / high_distance) * 100) / 100
    return capped_wfa(age, weight, gender)

def d2_zScoreWFA(age, weight, gender):
    return capped_wfa(age, weight, gender, RAW_TABLES)

def d2_oizp(value):
    return 1.0 if value is not None and float(value) >= 0 else 0.0

def dob_for_age(age):
    month = EVENT_DATE.month - age
    year = EVENT_DATE.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, EVENT_DATE.day)

def d2_monthsBetween(start, end):
    months = (end.year - start.year) * 12 + end.month - start.month
    return months - (end.day < start.day)

def formula_code(formula_path):
    formula = formula_path.read_text().strip()
    python = re.sub(r"[#AV]\{([^}]+)\}", r"\1", formula)
    python = python.replace("d2:", "d2_").replace("&&", " and ").replace("||", " or ")
    return len(formula), compile(python, str(formula_path), "eval")

def generated_value(code, gender, age, weight):
    env = {
        "__builtins__": {},
        "d2_ceil": math.ceil,
        "d2_floor": math.floor,
        "d2_monthsBetween": d2_monthsBetween,
        "d2_oizp": d2_oizp,
        "d2_zScoreWFA": d2_zScoreWFA,
        "event_date": EVENT_DATE,
        "var_age_in_months_otp": dob_for_age(age),
        "var_gender_otp": gender,
        "var_sex_otp": gender,
        "var_weight_otp": weight,
    }
    return float(eval(code, env))

def verify(formula_path):
    formula_len, code = formula_code(formula_path)
    print(f"Parsing formula: {formula_path} ({formula_len} characters)")
    print("Table repair: filled WFA boy age 28 by midpoint interpolation from ages 27 and 29.")
    total = 0
    failures = []

    for gender in (0, 1):
        for age in AGES:
            for weight_tenths in WEIGHTS:
                weight = weight_tenths / 10
                expected = expected_wfa(age, weight, gender)
                generated = generated_value(code, gender, age, weight)
                total += 1
                if abs(expected - generated) > TOL:
                    failures.append(
                        f"gender={gender} age={age:.1f} weight={weight:.1f} "
                        f"expected={expected} generated={generated}"
                    )

    print("Grid: genders=2, ages=0..60mo step=1mo, weights=0.1..40.0kg step=0.1kg")
    print(f"Cases: total={total}")
    if failures:
        print(f"FAIL: {len(failures)} mismatches")
        print("\n".join(failures[:20]))
        return 1

    print("PASS: generated formula matches the table-based uncapped WFA reference.")
    return 0

def main():
    return verify(Path(sys.argv[1]))

if __name__ == "__main__":
    raise SystemExit(main())
