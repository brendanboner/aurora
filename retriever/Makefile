# =============================================================================
# Retriever Service Makefile
# =============================================================================

.PHONY: help test install clean-venv

# Service-specific configuration
SERVICE_NAME := aurora-retriever
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
	@echo "$(CYAN)Retriever Service Makefile$(NC)"
	@echo ""
	@echo "Available commands:"
	@echo "  make test        - Run tests with pytest (creates venv automatically)"
	@echo "  make build-push  - Build and push Docker image to ECR"
	@echo "  make push        - Run tests, build, and push to ECR"
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
	@# Install requirements but skip the -e lines (they have wrong paths for local dev)
	@grep -v "^-e " requirements.txt | $(PIP) install -r /dev/stdin
	@# Install local packages with correct relative paths
	@$(PIP) install -e ../neo4j-client
	@$(PIP) install -e ../rabbitmq-client

# Run tests in venv
test: install
	@echo "$(CYAN)Running retriever service tests...$(NC)"
	@PYTHONPATH=..:$$PYTHONPATH $(PYTEST) tests/ -v --cov=scrapers --cov-report=term-missing
	@echo "$(GREEN)✓ Tests completed$(NC)"
	@$(MAKE) clean-venv

# Clean up virtual environment
clean-venv:
	@echo "$(CYAN)Cleaning up virtual environment...$(NC)"
	@rm -rf $(VENV)
	@echo "$(GREEN)✓ Virtual environment removed$(NC)"
