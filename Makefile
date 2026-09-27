# Variables
PYTHON = python3
PIP = pip3
SRC_DIR = src
MAIN = $(SRC_DIR)/main.py

.PHONY: install run debug clean lint

install:
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) $(MAIN) $(ARGS)

debug:
	$(PYTHON) -m pdb $(MAIN) $(ARGS)

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	rm -rf .pytest_cache

lint:
	flake8 .
	mypy --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs .