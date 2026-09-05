# Woodpecker CI MCP Server Makefile
# --------------------------------------------------
# This Makefile provides targets for the Woodpecker MCP server.
# It includes common functionality from ../mcp-common.mk
# --------------------------------------------------

# MCP configuration
AGENT_NAME = woodpecker

# Include common functionality
include ../mcp-common.mk

# Test targets
.PHONY: test test-verbose

test: setup-uv uv-venv ## Run all tests
	@echo "Running Woodpecker MCP tests..."
	@uv sync --all-groups
	@export WOODPECKER_API_URL="https://localhost:9443" && \
	export WOODPECKER_API_TOKEN="dummy-token-for-testing" && \
	cd tests && \
	uv run python run_all_tests.py

test-verbose: setup-uv uv-venv ## Run all tests with verbose output
	@echo "Running Woodpecker MCP tests with verbose output..."
	@uv sync --all-groups
	@export WOODPECKER_API_URL="https://localhost:9443" && \
	export WOODPECKER_API_TOKEN="dummy-token-for-testing" && \
	cd tests && \
	uv run python -v run_all_tests.py
