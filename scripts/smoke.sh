#!/usr/bin/env sh
# Offline presentation checks. Python 3.11+ and Node 18+; no package installation.
set -eu
cd "$(dirname "$0")/.."
"${PYTHON_BIN:-python}" -m unittest discover -s tests -p test_dashboard.py -v
"${PYTHON_BIN:-python}" -m unittest discover -s tests -p test_clinical_reports.py -v
"${NODE_BIN:-node}" --test tests/test_dashboard_model.cjs
"${NODE_BIN:-node}" --test tests/test_presentation.cjs
"${NODE_BIN:-node}" --test tests/test_report_ui.cjs
"${NODE_BIN:-node}" --check phage_lab/web/app.js
"${NODE_BIN:-node}" --check phage_lab/web/report-ui.js
