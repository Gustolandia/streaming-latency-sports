# Streaming Latency Sports - Test Suite
# ========================================
# 
# This test suite provides comprehensive testing for the benchmark suite.
# 
# Structure:
#   tests/
#   ├── __init__.py          - Test configuration and fixtures
#   ├── conftest.py          - Pytest fixtures
#   ├── unit/
#   │   ├── __init__.py
#   │   ├── test_*.py        - Unit tests for individual functions
#   └── integration/
#       ├── __init__.py
#       └── test_*.py        - Integration tests for workflows
#
# Run all tests:
#   pytest tests/ -v
#
# Run with coverage:
#   pytest tests/ --cov=scripts --cov-report=html
