#!/usr/bin/env python3
"""Generates the WHO LMS based WFH DHIS2 program rule expression for OTP program.

Dependencies:
pandas - for parsing the .dta files - see usage below.

Usage:
python3 -m venv .venv
.venv/bin/python -m pip install pandas
.venv/bin/python z-score-wfh-generate-who-lms.py wflanthro.dta wfhanthro.dta formula.txt
(the .dta files can be found, for example, on github.com/unicef-drp/igrowup_update)

Inputs:
#{var_weight_otp} (kg), #{var_height_otp} (cm), A{var_sex_otp} (male/female).

Notes:
1. No "Height or length" field needed: it takes WFL below 87 cm, otherwise WFH.
2. DHIS2 math truncates fractional exponents, so polynomial approximation is used.
"""

import argparse
import math
from dataclasses import dataclass
from pathlib import Path


WEIGHT = "#{var_weight_otp}"
HEIGHT = "#{var_height_otp}"
SEX = "A{var_sex_otp}"
HEIGHT10 = f"({HEIGHT}*10)"
EPSILON = "1e-6"  # exact grid tolerance, in height * 10
EXP_POLYNOMIAL_DEGREE = 32


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


def coefficients(row: Row) -> dict[str, float]:
    L, M, S = row.l, row.m, row.s

    def sd_weight(z: int) -> float:
        return M * (1 + L * S * z) ** (1 / L)

    sd3n, sd2n = sd_weight(-3), sd_weight(-2)
    sd2p, sd3p = sd_weight(2), sd_weight(3)
    lower_width = sd2n - sd3n
    upper_width = sd3p - sd2p
    return {
        "a": M ** (-L) / (S * L),
        "b": -1 / (S * L),
        "lower_slope": 1 / lower_width,
        "lower_intercept": -3 - sd3n / lower_width,
        "upper_slope": 1 / upper_width,
        "upper_intercept": 3 - sd3p / upper_width,
        "sd3n": sd3n,
        "sd3p": sd3p,
    }


def number(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".10g")


def choose(test: str, yes: str, no: str, quote: str = "'") -> str:
    return f"d2:condition({quote}{test}{quote},{yes},{no})"


def weight_power(L: float) -> str:
    def select(values: list[float]) -> str:
        result = number(values[-1])
        for boundary, value in reversed(list(zip((4, 8, 16), values[:-1]))):
            result = choose(f"{WEIGHT}<{boundary}", number(value), result)
        return result

    scales = [3.0, 6.0, 12.0, 24.0]
    x = f"({WEIGHT}/{select(scales)}-1)"
    terms = [1.0]
    for degree in range(1, EXP_POLYNOMIAL_DEGREE + 1):
        terms.append(terms[-1] * (L - degree + 1) / degree)
    polynomial = number(terms[-1])
    for term in reversed(terms[:-1]):
        polynomial = f"({number(term)}+{x}*{polynomial})"
    return f"({select([scale**L for scale in scales])}*{polynomial})"


def table_lookup(rows: list[Row], values: list[str], side: str) -> str:
    if all(value == values[0] for value in values):
        return values[0]
    middle = len(rows) // 2
    boundary = rows[middle]
    if boundary.reference == 1 and boundary.key == 870:
        test = f"{HEIGHT}<87"
    elif side == "low":
        threshold = (boundary.key - float(EPSILON)) / 10
        test = f"{HEIGHT}<={threshold:.7f}"
    else:
        threshold = (boundary.key - 1 + float(EPSILON)) / 10
        test = f"{HEIGHT}<{threshold:.7f}"
    left = table_lookup(rows[:middle], values[:middle], side)
    right = table_lookup(rows[middle:], values[middle:], side)
    return choose(test, left, right, '"')


def endpoint(rows: list[Row], parameters: list[dict[str, float]], power: str, side: str) -> str:
    def lookup(name: str) -> str:
        return table_lookup(rows, [number(row[name]) for row in parameters], side)

    central = f"({lookup('a')}*{power}+{lookup('b')})"
    lower = f"({lookup('lower_slope')}*{WEIGHT}+{lookup('lower_intercept')})"
    upper = f"({lookup('upper_slope')}*{WEIGHT}+{lookup('upper_intercept')})"
    return choose(f"{WEIGHT}<{lookup('sd3n')}", lower,
                  choose(f"{WEIGHT}>{lookup('sd3p')}", upper, central))


def generate_expression(rows: list[Row]) -> str:
    floor = f"d2:floor({HEIGHT10})"
    below_next = f"({floor}+1-{HEIGHT10})"
    above_floor = f"({HEIGHT10}-{floor})"
    low_key = f"({floor}+1-d2:oizp({below_next}-{EPSILON}))"
    off_grid = f"(d2:oizp({above_floor}-{EPSILON})*d2:oizp({below_next}-{EPSILON}))"
    fraction = f"({off_grid}*(({HEIGHT}-({low_key}/10))/0.1))"

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
        parameters = [coefficients(row) for row in selected]
        power = weight_power(L)
        low = endpoint(selected, parameters, power, "low")
        high = endpoint(selected, parameters, power, "high")

        expressions.append(f"((1-{fraction})*{low}+{fraction}*{high})")
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
