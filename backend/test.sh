#!/bin/bash

# Test script for X Terminal backend
echo "Running tests for X Terminal backend..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Run setup.sh first."
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Run tests
python -m pytest

echo "Tests completed!"
