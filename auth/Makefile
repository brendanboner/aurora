.PHONY: test test-unit test-integration coverage clean

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
PYTEST = $(VENV)/bin/pytest

# Create virtual environment (use Python 3.12 for pydantic compatibility)
$(VENV)/bin/activate:
	python3.12 -m venv $(VENV)

# Install dependencies in venv
install: $(VENV)/bin/activate
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

# Run all tests in a fresh venv
test: install
	$(PYTEST)
	$(MAKE) clean-venv

# Run unit tests only
test-unit: install
	$(PYTEST) tests/test_oauth.py tests/test_middleware.py
	$(MAKE) clean-venv

# Run integration tests only
test-integration: install
	$(PYTEST) tests/test_endpoints.py tests/test_proxy.py
	$(MAKE) clean-venv

# Generate coverage report
coverage: install
	$(PYTEST) --cov=. --cov-report=html --cov-report=term --cov-config=tests/.coveragerc
	$(MAKE) clean-venv

# Clean Python artifacts
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf tests/.pytest_cache tests/.coverage tests/htmlcov
	rm -rf .pytest_cache .coverage htmlcov  # Clean old locations too

# Clean virtual environment
clean-venv:
	rm -rf $(VENV)

# Clean everything
clean-all: clean clean-venv
