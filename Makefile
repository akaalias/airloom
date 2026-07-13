PYTHON ?= python3
VENV := .venv
PIP := $(VENV)/bin/pip
FRAMEVO := $(VENV)/bin/airloom

.PHONY: install test demo clean

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip

install: $(VENV)/bin/activate
	$(PIP) install -e ".[dev]"

test: install
	$(VENV)/bin/pytest -q

# 3 generations, population 8 -- finishes in well under 10 minutes on 8 cores,
# prints the leaderboard and the file:// path to the live gallery.
demo: install
	$(FRAMEVO) run --generations 3 --population 8 --run-id demo

clean:
	rm -rf $(VENV) build *.egg-info src/airloom/__pycache__ tests/__pycache__
