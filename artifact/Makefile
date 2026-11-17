# LeaseMem-Mobile artifact. `make all` regenerates every derived CSV, table, figure and macro from the raw logs
# and rebuilds the paper. `make apks` rebuilds the three apps; `make emulator-runs` documents the live runs.
PY ?= python3
# E5 needs a python environment with an android_world checkout (pinned commit 55ddaf5e) importable; set AW_CHECKOUT too
AW_PYTHON ?= ../../shared-android/venv/bin/python
all: analyze render paper
analyze:
	$(PY) scripts/analyze.py > results/derived/analyze_stdout.txt
render:
	$(PY) scripts/render.py
	$(PY) revision/oracle.py
	$(PY) revision/deployment_summary.py >/dev/null
	$(PY) followup/analyze.py
	$(PY) physical/analyze_phys.py
census:
	$(AW_PYTHON) scripts/aw_census.py
paper:
	cd ../manuscript && pdflatex -halt-on-error -interaction=nonstopmode main >/dev/null && bibtex main >/dev/null && pdflatex -halt-on-error -interaction=nonstopmode main >/dev/null && pdflatex -halt-on-error -interaction=nonstopmode main >/dev/null && pdfinfo main.pdf | grep Pages
apks:
	cd app/client && ./build.sh LeaseMemClient-v4
	cd app/trig && ./build.sh
	cd app/mut && ./build.sh
	cd app/assist && ./build.sh
	cd app/persist && ./build.sh
	cd app/fgs35 && ./build.sh
check-determinism:
	$(PY) revision/determinism.py
# fails while the PDF still shows a red TBD (physical-phone numbers not yet measured)
check-final:
	$(PY) physical/analyze_phys.py --self-check
	$(PY) scripts/check_final.py
.PHONY: all analyze render census paper apks check-determinism check-final
