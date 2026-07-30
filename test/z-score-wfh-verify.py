#!/usr/bin/env python3
"""
Verifies a generated uncapped WFH z-score formula for OTP.

Usage:

    python3 z-score-wfh-verify.py z-score-wfh-formula-otp.txt

The verifier checks the generated formula over:

    genders: male, female
    heights: 45..120 cm, 1 cm step
    weights: 0.1..40.0 kg, 0.1 kg step

It compares the generated formula with DHIS2's official capped WFH formula
whenever the generated result is still inside the official [-3.5, 3.5] range,
and whenever the official result is strictly inside that range, while allowing
the intentional uncapped tail beyond +/-3.5.
"""

import math
import re
import sys
from collections import namedtuple
from pathlib import Path
from urllib.request import urlopen

WEIGHTS = range(1, 401)
HEIGHTS = range(45, 121)
CAP = 3.5
TOL = 1e-9
TABLE_URL = "https://github.com/dhis2/expression-parser/blob/v1.4.2/src/commonMain/kotlin/org/hisp/dhis/lib/expression/math/ZScoreTable.kt"
GENDER_SELECTOR = 'd2:countIfValue(A{var_sex_otp},"male")'
ROW_RE = re.compile(
    r"addEntry\(res,\s*(?P<sex>[01]),\s*(?P<height>[0-9.]+),\s*"
    r"newSDMap\((?P<values>[^)]*)\)\)"
)
Row = namedtuple("Row", "height sd3neg sd2neg sd1neg sd0 sd1 sd2 sd3")

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
        "m": parse_table(source, "newZScoreWFHTableBoy", "0"),
        "f": parse_table(source, "newZScoreWFHTableGirl", "1"),
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
            values = [num(match["height"])] + [
                num(value) for value in match["values"].split(",")
            ]
            row = Row(*values)
            rows[int(round(row.height * 2))] = row

    assert sexes == {expected_sex} and sorted(rows) == list(range(90, 241)), (
        f"{function_name}: unexpected WFH table shape"
    )
    return rows

TABLES = fetch_tables()

def gender_key(gender):
    if isinstance(gender, bool):
        gender = str(gender).lower()
    elif isinstance(gender, (int, float)) and float(gender).is_integer():
        gender = str(int(gender))
    return "m" if str(gender) in {"male", "MALE", "Male", "ma", "m", "M", "0", "false"} else "f"

def official_wfh(height, weight, gender):
    row = TABLES[gender_key(gender)][int(round(height * 2))]
    keys = [row.sd3neg, row.sd2neg, row.sd1neg, row.sd0, row.sd1, row.sd2, row.sd3]
    sds = dict(zip(keys, [3, 2, 1, 0, 1, 2, 3]))
    factor = (weight > row.sd0) - (weight < row.sd0)

    for key, sd in sds.items():
        if abs(weight - key) < TOL:
            return float(sd * factor)
    if weight > row.sd3:
        return CAP
    if weight < row.sd3neg:
        return -CAP

    lower, higher = keys[0], keys[-1]
    for key in keys:
        if weight > key:
            lower = key
        else:
            higher = key
            break

    distance = higher - lower
    raw = (
        sds[lower] + (weight - lower) / distance
        if weight > row.sd0
        else sds[higher] + (higher - weight) / distance
    )
    return math.trunc(raw * factor * 100) / 100

def d2_oizp(value):
    return 1.0 if value is not None and float(value) >= 0 else 0.0

def d2_countIfValue(value, sample):
    return int(value == sample)

def formula_code(formula_path):
    formula = formula_path.read_text().strip()
    assert "d2:condition" not in formula
    assert formula.count(GENDER_SELECTOR) == 2, "formula must select the male table for code 'male'"
    python = re.sub(r"#\{([^}]+)\}", r"\1", formula)
    python = re.sub(r"A\{([^}]+)\}", r"\1", python)
    python = python.replace("d2:", "d2_").replace("&&", " and ").replace("||", " or ")
    return len(formula), compile(python, str(formula_path), "eval")

def generated_value(code, gender, height, weight):
    env = {
        "__builtins__": {},
        "d2_floor": math.floor,
        "d2_ceil": math.ceil,
        "d2_countIfValue": d2_countIfValue,
        "d2_oizp": d2_oizp,
        "d2_zScoreWFH": official_wfh,
        "var_gender_otp": gender,
        "var_sex_otp": gender,
        "var_height_otp": height,
        "var_weight_otp": weight,
    }
    return float(eval(code, env))

def verify(formula_path):
    formula_len, code = formula_code(formula_path)
    print(f"Parsing formula: {formula_path} ({formula_len} characters)")
    total = compared = skipped = 0
    failures = []

    for gender in ("male", "female"):
        for height in HEIGHTS:
            for weight_tenths in WEIGHTS:
                weight = weight_tenths / 10
                official = official_wfh(math.floor(height * 2) / 2, weight, gender)
                generated = generated_value(code, gender, float(height), weight)
                total += 1

                if abs(official) < CAP - TOL or abs(generated) <= CAP + TOL:
                    compared += 1
                    if abs(official - generated) > TOL:
                        failures.append(
                            f"gender={gender} height={height:.1f} weight={weight:.1f} "
                            f"official={official} generated={generated}"
                        )
                else:
                    skipped += 1

    print("Grid: genders=2, heights=45..120cm step=1cm, weights=0.1..40.0kg step=0.1kg")
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
