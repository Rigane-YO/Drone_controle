PYTHON = python3
MAIN = src/main.py
LINT_DIRS = src/

.PHONY: all run lint clean fclean re

all:
	@echo "Rien à compiler (Python). Utilisez 'make run ARGS=\"chemin/carte.txt\"' ou 'make lint'."

run:
	$(PYTHON) $(MAIN) $(ARGS)

lint:
	@echo "Vérification avec flake8..."
	flake8 $(LINT_DIRS)
	@echo "Vérification du typage strict avec mypy..."
	mypy --strict $(MAIN)

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +

fclean: clean

re: clean all