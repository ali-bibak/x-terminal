#!/bin/bash

# Test script for X Terminal backend
echo "Running tests for X Terminal backend..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Run setup.sh first."
    exit 1
fi

# Run tests using venv's Python directly (more reliable than source activate)
./venv/bin/python -m pytest --disable-warnings "$@"

echo "Tests completed!"
