PY ?= python3
SRC := src

.PHONY: help install demo test clean

help:
	@echo "make demo   - corre el pipeline completo con datos sintéticos (sin API keys)"
	@echo "make test   - corre la suite de tests (unittest, sin dependencias)"
	@echo "make install- instala el paquete en modo editable"
	@echo "make clean  - borra artefactos y la base de datos local"

demo:
	PYTHONPATH=$(SRC) $(PY) -m alphaconsensus demo

test:
	PYTHONPATH=$(SRC) $(PY) -m unittest discover -s tests -v

install:
	$(PY) -m pip install -e ".[dev]"

clean:
	rm -rf data/*.db data/*.json build dist *.egg-info src/*.egg-info
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
