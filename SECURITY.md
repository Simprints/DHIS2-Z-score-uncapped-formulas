# Security Policy

## Supported Versions

This project is a small collection of scripts and generated DHIS2 program-rule
formulas. Security fixes are applied to the latest state of the `main` branch
only.

| Version        | Supported          |
| -------------- | ------------------ |
| `main` (latest)| :white_check_mark: |
| Older commits  | :x:                |

## Reporting a Vulnerability

Please **do not** report security vulnerabilities through public GitHub issues.

Instead, report them privately using GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
feature:

1. Go to the **Security** tab of this repository.
2. Click **Report a vulnerability**.

When reporting, please include:

- A description of the issue and its potential impact.
- Steps to reproduce, or a proof of concept.
- Any relevant versions, commit SHAs, or environment details.

We aim to acknowledge reports within **5 business days** and to provide a
remediation timeline after triage.

## Scope

This repository contains Python scripts that generate DHIS2 program-rule
expressions and validation scripts that verify them. Things especially worth
reporting:

- Issues that could cause the generation or verification scripts to execute
  untrusted code (for example, weaknesses in how generated formulas are parsed
  or evaluated).
- Correctness flaws in the generated formulas that could lead to incorrect
  clinical z-score values.

The scripts fetch reference data over HTTPS from the public DHIS2
`expression-parser` repository, pinned to a specific tag. Reports about that
upstream dependency should be directed to the
[DHIS2 project](https://github.com/dhis2).
