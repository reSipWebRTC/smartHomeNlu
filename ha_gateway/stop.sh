#!/bin/bash

# Home Assistant Gateway Stop Script

# Default port
PORT=8124

# Find gateway processes
PIDS=$(pgrep -f "python.*ha_gateway.server")

if [[ -z "$PIDS" ]]; then
    echo "No Home Assistant Gateway process found."
    exit 0
fi

echo "Found Home Assistant Gateway processes:"
echo "$PIDS"
echo ""

# Kill processes
for PID in $PIDS; do
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping process $PID..."
        kill "$PID"

        # Wait for process to terminate
        for i in {1..10}; do
            if ! kill -0 "$PID" 2>/dev/null; then
                echo "Process $PID stopped successfully"
                break
            fi
            sleep 1
        done

        # Force kill if still running
        if kill -0 "$PID" 2>/dev/null; then
            echo "Force killing process $PID..."
            kill -9 "$PID"
        fi
    fi
done

# Alternative: Find by port
echo ""
echo "Checking for processes using port $PORT..."
PORT_PIDS=$(lsof -ti:$PORT 2>/dev/null)

if [[ -n "$PORT_PIDS" ]]; then
    echo "Found processes using port $PORT: $PORT_PIDS"
    for PID in $PORT_PIDS; do
        if kill -0 "$PID" 2>/dev/null; then
            echo "Killing process $PID..."
            kill -9 "$PID"
        fi
    done
fi

echo "Home Assistant Gateway stopped."