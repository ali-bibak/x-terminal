#!/bin/bash

# Setup script for X Terminal backend
echo "Setting up X Terminal backend environment..."

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

echo "Setup complete! Activate the environment with: source venv/bin/activate"
echo "Run the Grok adapter CLI with: python -m adapter.grok.cli"
echo "Run the X adapter CLI with: python -m adapter.x.cli"
echo "Run tests with: python -m pytest"
