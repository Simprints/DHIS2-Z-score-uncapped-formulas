#!/usr/bin/env python3
"""
Verifies a generated uncapped HFA z-score formula for OTP.

Usage:

    python3 z-score-hfa-verify.py z-score-hfa-formula-otp.txt

The verifier checks the generated formula over:

    genders: 0, 1
    ages: 0..60 months, 1 month step
    heights: 30.0..140.0 cm, 0.5 cm step

It compares the generated formula with DHIS2's official capped HFA formula
whenever the generated result is still inside the official [-3.5, 3.5] range,
and whenever the result is strictly inside that range, while allowing intentional uncapped tail beyond +/-3.5.
"""

import math
from datetime import date
import re
import sys
from collections import namedtuple
from pathlib import Path
from urllib.request import urlopen

AGES = list(range(0, 61))
HEIGHTS = [i / 2 for i in range(60, 281)]
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
    return {
        "m": parse_table(source, "newZScoreHFATableBoy", "0"),
        "f": parse_table(source, "newZScoreHFATableGirl", "1"),
    }

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
            values = [num(match["age"])] + [
                num(value) for value in match["values"].split(",")
            ]
            row = Row(*values)
            rows[int(row.age)] = row

    assert sexes == {expected_sex} and sorted(rows) == list(range(0, 61)), (
        f"{function_name}: unexpected HFA table shape"
    )
    return rows

TABLES = fetch_tables()

def gender_key(gender):
    if isinstance(gender, bool):
        gender = str(gender).lower()
    elif isinstance(gender, (int, float)) and float(gender).is_integer():
        gender = str(int(gender))
    return "m" if str(gender) in {"male", "MALE", "Male", "ma", "m", "M", "0", "false"} else "f"

def official_hfa(age, height, gender):
    row = TABLES[gender_key(gender)][int(math.floor(age))]
    keys = [row.sd3neg, row.sd2neg, row.sd1neg, row.sd0, row.sd1, row.sd2, row.sd3]
    sds = dict(zip(keys, [3, 2, 1, 0, 1, 2, 3]))
    factor = (height > row.sd0) - (height < row.sd0)

    for key, sd in sds.items():
        if abs(height - key) < TOL:
            return float(sd * factor)
    if height > row.sd3:
        return CAP
    if height < row.sd3neg:
        return -CAP

    lower, higher = keys[0], keys[-1]
    for key in keys:
        if height > key:
            lower = key
        else:
            higher = key
            break

    distance = higher - lower
    raw = (
        sds[lower] + (height - lower) / distance
        if height > row.sd0
        else sds[higher] + (higher - height) / distance
    )
    return math.trunc(raw * factor * 100) / 100

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

def generated_value(code, gender, age, height):
    env = {
        "__builtins__": {},
        "d2_floor": math.floor,
        "d2_ceil": math.ceil,
        "d2_oizp": d2_oizp,
        "d2_monthsBetween": d2_monthsBetween,
        "d2_zScoreHFA": official_hfa,
        "event_date": EVENT_DATE,
        "var_age_in_months_otp": dob_for_age(age),
        "var_gender_otp": gender,
        "var_sex_otp": gender,
        "var_height_otp": height,
    }
    return float(eval(code, env))

def verify(formula_path):
    formula_len, code = formula_code(formula_path)
    print(f"Parsing formula: {formula_path} ({formula_len} characters)")
    total = compared = skipped = 0
    failures = []

    for gender in (0, 1):
        for age in AGES:
            for height in HEIGHTS:
                official = official_hfa(math.floor(age), height, gender)
                generated = generated_value(code, gender, age, height)
                total += 1

                if abs(official) < CAP - TOL or abs(generated) <= CAP + TOL:
                    compared += 1
                    if abs(official - generated) > TOL:
                        failures.append(
                            f"gender={gender} age={age:.1f} height={height:.1f} "
                            f"official={official} generated={generated}"
                        )
                else:
                    skipped += 1

    print("Grid: genders=2, ages=0..60mo step=1mo, heights=30.0..140.0cm step=0.5cm")
    print(f"Cases: total={total}, compared={compared}, skipped_uncapped_tail={skipped}")
    if failures:
        print(f"FAIL: {len(failures)} mismatches")
        return 1

    print("PASS: generated formula matches the official formula everywhere it should remain capped/in-range.")
    return 0

def main():
    return verify(Path(sys.argv[1]))

if __name__ == "__main__":
    raise SystemExit(main())
