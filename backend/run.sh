#!/bin/bash

# Run script for X Terminal backend
echo "Starting X Terminal backend..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Run setup.sh first."
    exit 1
fi

# Check for .env file
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found. Copy .env.example to .env and configure API keys."
fi

# Default values
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
RELOAD="${RELOAD:-true}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --no-reload)
            RELOAD="false"
            shift
            ;;
        --prod)
            RELOAD="false"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./run.sh [--port PORT] [--host HOST] [--no-reload] [--prod]"
            exit 1
            ;;
    esac
done

# Build uvicorn command
CMD="./venv/bin/uvicorn main:app --host $HOST --port $PORT"

if [ "$RELOAD" = "true" ]; then
    CMD="$CMD --reload"
fi

echo "Running: $CMD"
echo "API docs: http://$HOST:$PORT/docs"
echo ""

# Run the server
exec $CMD

