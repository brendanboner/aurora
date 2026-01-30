# =============================================================================
# Oracle Service Makefile
# =============================================================================

.PHONY: help test install clean-venv

# Service-specific configuration
SERVICE_NAME := aurora-oracle
DOCKERFILE := Dockerfile
BUILD_CONTEXT := ..

# Virtual environment configuration
VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
PYTEST = $(VENV)/bin/pytest

# Load common configuration and targets (build, push, push-only, clean)
include ../Makefile.common

help:
	@echo "$(CYAN)Oracle Service Makefile$(NC)"
	@echo ""
	@echo "Available commands:"
	@echo "  make test        - Run tests with pytest (creates venv automatically)"
	@echo "  make build-push  - Build and push Docker image to ECR (skips tests)"
	@echo "  make ship        - Run tests, build, and push to ECR"
	@echo "  make clean       - Clean up test artifacts"
	@echo "  make clean-venv  - Remove virtual environment"

# Create virtual environment (use Python 3.12 for better compatibility with dependencies)
$(VENV)/bin/activate:
	@echo "$(CYAN)Creating virtual environment with Python 3.12...$(NC)"
	@python3.12 -m venv $(VENV) || python3 -m venv $(VENV)

# Install dependencies in venv
install: $(VENV)/bin/activate
	@echo "$(CYAN)Installing dependencies...$(NC)"
	@$(PIP) install --upgrade pip
	@$(PIP) install -r requirements.txt
	@$(PIP) install -e ../neo4j-client

# Run tests in venv
test: install
	@echo "$(CYAN)Running oracle service tests...$(NC)"
	@PYTHONPATH=..:$$PYTHONPATH $(PYTEST) tests/ -v --cov=src --cov-report=term-missing
	@echo "$(GREEN)✓ Tests completed$(NC)"
	@$(MAKE) clean-venv

# Override clean to also clean venv artifacts
clean:
	@echo "$(CYAN)Cleaning $(SERVICE_NAME) artifacts...$(NC)"
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf tests/.pytest_cache tests/.coverage tests/htmlcov
	@rm -rf .pytest_cache .coverage htmlcov
	@rm -rf build .cache
	@echo "$(GREEN)✓ Cleanup completed$(NC)"

# Clean virtual environment
clean-venv:
	@echo "$(CYAN)Removing virtual environment...$(NC)"
	@rm -rf $(VENV)
	@echo "$(GREEN)✓ Virtual environment removed$(NC)"
