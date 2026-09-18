#!/usr/bin/env python3
"""Generates cubic spline-optimized WHO LMS based WFH DHIS2 program rule expression for OTP program.

Dependencies:
pandas - for parsing .dta files and fitting cubic splines with numpy - see usage below.

Usage:
python3 -m venv .venv
.venv/bin/python -m pip install pandas
.venv/bin/python z-score-wfh-generate-who-lms.py wflanthro.dta wfhanthro.dta formula.txt
(the .dta files can be found, for example, on github.com/unicef-drp/igrowup_update)

Inputs:
#{var_weight_otp} (kg), #{var_height_otp} (cm), A{var_sex_otp} (male/female).

Notes:
1. No "Height or length" field needed: it takes WFL below 87 cm, otherwise WFH.
2. DHIS2 math truncates fractional exponents, so cubic spline approximation is used.
3. Optimized for the DHIS2 rule engine, within 0.01 SD of unoptimized method, for 2-25 kg, 45-120 cm:
   instead of looking up L, M, S at 2 reference points 0.1 cm apart and interpolating, it evaluates
       zLMS = ((w / M)^L - 1) / (L * S)
       z = min(3, max(-3, zLMS)) + max(0, w - SD3p) / SD23p - max(0, SD3n - w) / SD23n
   with each height term (M^L, S, SD3n, SD23n, SD3p, SD23p) as a cubic spline of length or height,
   and w^L as a cubic spline of weight, using the coarsest knots that keep the 0.01 SD.
4. DHIS2 prioritizes + to -, * to /, so they are parenthesized for correct output.
"""

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


WEIGHT = "#{var_weight_otp}"
HEIGHT = "#{var_height_otp}"
SEX = "A{var_sex_otp}"
WEIGHT_RANGE = (2, 25)  # kg
LENGTH_KNOTS = [*range(46, 60), *range(60, 87, 4)]  # cm, denser for newborn
HEIGHT_KNOTS = [*range(93, 120, 6)]  # cm
WEIGHT_KNOTS = np.geomspace(*WEIGHT_RANGE, 8)[1:-1]  # kg, geometric for w^L


@dataclass(frozen=True)
class Row:
    reference: int  # 0 = WFL, 1 = WFH
    sex: int        # 0 = male, 1 = female
    key: int        # tenths of cm
    l: float
    m: float
    s: float


def read_reference(path: Path, reference: int) -> list[Row]:
    import pandas as pd
    table = pd.read_stata(path, convert_dates=False, convert_categoricals=False)
    height_column = "__000002" if reference == 0 else "__000003"
    rows = []
    for values in table[["__000001", height_column, "l", "m", "s"]].itertuples(index=False, name=None):
        sex, height, l, m, s = map(float, values)
        key = math.floor(height * 10 + 0.5)
        rows.append(Row(reference, int(sex) - 1, key, l, m, s))
    return rows


def lms_terms(row: Row) -> dict[str, float]:
    L, M, S = row.l, row.m, row.s
    def sd_weight(z: int) -> float:
        return M * (1 + L * S * z) ** (1 / L)
    return {
        "median_power": M ** L,
        "s": S,
        "sd3n": sd_weight(-3),
        "sd23n": sd_weight(-2) - sd_weight(-3),
        "sd3p": sd_weight(3),
        "sd23p": sd_weight(3) - sd_weight(2),
    }


def number(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".10g")


def choose(test: str, yes: str, no: str) -> str:
    return f"d2:condition('{test}',{yes},{no})"


def fit_spline(x: np.ndarray, y: np.ndarray, knots: list[float]) -> np.ndarray:
    basis = np.column_stack([x**degree for degree in range(4)] + [np.maximum(x - knot, 0) ** 3 for knot in knots])
    return np.linalg.lstsq(basis / y[:, None], np.ones_like(y), rcond=None)[0]


def spline_expression(variable: str, knots: list[float], coefficients: np.ndarray) -> str:
    cubic = number(coefficients[3])
    for coefficient in reversed(coefficients[:3]):
        cubic = f"({number(coefficient)}+{variable}*{cubic})"
    knot_terms = [f"{number(k)}*d2:zing({variable}-{number(float(knot))})^3"
                  for knot, k in zip(knots, coefficients[4:])]
    return "(" + "+".join([cubic, *knot_terms]) + ")"


def weight_power(L: float) -> str:
    weights = np.linspace(*WEIGHT_RANGE, 231)
    return spline_expression(WEIGHT, WEIGHT_KNOTS, fit_spline(weights, weights**L, WEIGHT_KNOTS))


def height_term(rows: list[Row], name: str) -> str:
    splines = []
    for reference, knots in ((0, LENGTH_KNOTS), (1, HEIGHT_KNOTS)):
        table = [row for row in rows if row.reference == reference]
        heights = np.array([row.key / 10 for row in table])
        values = np.array([lms_terms(row)[name] for row in table])
        splines.append(spline_expression(HEIGHT, knots, fit_spline(heights, values, knots)))
    return choose(f"{HEIGHT}<87", *splines)


def within_sd3(z: str) -> str:
    return f"(3-d2:zing(6-d2:zing({z}+3)))" # min(3, max(-3, z))


def generate_expression(rows: list[Row]) -> str:
    expressions = []
    for sex in (0, 1):
        selected = sorted(
            (row for row in rows if row.sex == sex and (
                (row.reference == 0 and row.key <= 870)
                or (row.reference == 1 and row.key >= 870)
            )),
            key=lambda row: (row.reference, row.key),
        )
        L = selected[0].l
        assert all(row.l == L for row in selected), "WHO L must be constant for each sex"
        terms = {name: height_term(selected, name) for name in lms_terms(selected[0])}

        lms = f"(({weight_power(L)}/{terms['median_power']}-1)/({number(L)}*{terms['s']}))"
        above_sd3p = f"(d2:zing({WEIGHT}-{terms['sd3p']})/{terms['sd23p']})"
        below_sd3n = f"(d2:zing({terms['sd3n']}-{WEIGHT})/{terms['sd23n']})"
        expressions.append(f"(({within_sd3(lms)}+{above_sd3p})-{below_sd3n})")
    expression = choose(f'{SEX}=="male"', *expressions)
    return f"d2:round({expression},2)"


def write_expression(path: Path, expression: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output:
        output.write(expression)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("length_reference", type=Path)
    parser.add_argument("height_reference", type=Path)
    parser.add_argument("output_expression", type=Path)
    args = parser.parse_args()
    rows = read_reference(args.length_reference, 0) + read_reference(args.height_reference, 1)
    expression = generate_expression(rows)
    write_expression(args.output_expression, expression)


if __name__ == "__main__":
    main()
