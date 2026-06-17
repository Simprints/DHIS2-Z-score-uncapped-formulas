# Contributing

Thanks for your interest in contributing! This project generates and verifies
"uncapped" DHIS2 z-score program-rule formulas. Contributions of all kinds are
welcome — bug reports, fixes, documentation improvements, and new validation
cases.

## Getting Started

The project uses **Python 3** (3.9+ recommended) and the standard library only —
no third-party dependencies are required.

```bash
git clone https://github.com/Simprints/Z-score-uncapped-formulas-DHIS2.git
cd Z-score-uncapped-formulas-DHIS2
```

### Generating formulas

Each generator prints a formula to stdout; redirect it to the matching file in
`output/`:

```bash
python3 z-score-hfa-generate.py > output/z-score-hfa-formula-otp.txt
python3 z-score-wfa-generate.py > output/z-score-wfa-formula-otp.txt
python3 z-score-wfh-generate.py > output/z-score-wfh-formula-otp.txt
```

The generators target the `otp` program. Formulas for `tsfp` or `ramp` are
produced by replacing every `_otp` substring with `_tsfp` or `_ramp`.

### Verifying formulas

The scripts in `test/` validate a generated formula against DHIS2's official
capped z-score logic across the full range of inputs:

```bash
python3 test/z-score-hfa-verify.py output/z-score-hfa-formula-otp.txt
python3 test/z-score-wfa-verify.py output/z-score-wfa-formula-otp.txt
python3 test/z-score-wfh-verify.py output/z-score-wfh-formula-otp.txt
```

A successful run prints `PASS`. Please make sure verification passes before
opening a pull request.

> Note: the generator and verifier scripts fetch the DHIS2 reference tables over
> HTTPS, so an internet connection is required to run them.

## Reporting Issues

When filing a bug, please include:

- What you ran and what you expected to happen.
- The actual output (including any `FAIL` lines from the verifiers).
- Your Python version and operating system.

## Security

Please do not file security vulnerabilities as public issues. See
[SECURITY.md](SECURITY.md) for how to report them privately.

## License

By contributing, you agree that your contributions will be licensed under the
same terms as the project (see [LICENSE](LICENSE)).
