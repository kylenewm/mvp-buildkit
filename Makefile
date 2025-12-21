.PHONY: install install-dev clean help

help:
	@echo "Available commands:"
	@echo "  make install      - Install the package"
	@echo "  make install-dev  - Install with dev dependencies"
	@echo "  make clean        - Remove build artifacts"

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf src/*.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

