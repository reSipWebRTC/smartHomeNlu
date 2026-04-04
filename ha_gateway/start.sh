#!/bin/bash

# Home Assistant Gateway Start Script

# Set default values
CONFIG_FILE="$HOME/.ha_gateway/config.yaml"
LOG_FILE="$HOME/.ha_gateway.log"
PYTHON_CMD="python3"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --log-file)
            LOG_FILE="$2"
            shift 2
            ;;
        --python)
            PYTHON_CMD="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --config FILE     Configuration file (default: ~/.ha_gateway/config.yaml)"
            echo "  --log-file FILE   Log file (default: ~/.ha_gateway.log)"
            echo "  --python CMD      Python command (default: python3)"
            echo "  --help, -h        Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check if Python is available
if ! command -v $PYTHON_CMD &> /dev/null; then
    echo "Error: Python not found. Please install Python 3.7+."
    exit 1
fi

# Check if required modules are installed
$PYTHON_CMD -c "import aiohttp, yaml" 2>/dev/null || {
    echo "Installing required packages..."
    $PYTHON_CMD -m pip install -r requirements.txt
}

# Create config directory if it doesn't exist
mkdir -p "$(dirname "$CONFIG_FILE")"

# Create default config if it doesn't exist
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Creating default configuration file at $CONFIG_FILE"
    cp "$(dirname "$0")/example_config.yaml" "$CONFIG_FILE"
    echo "Please edit $CONFIG_FILE with your Home Assistant details before starting the gateway."
    exit 0
fi

# Start the gateway
echo "Starting Home Assistant Gateway..."
echo "Config: $CONFIG_FILE"
echo "Log: $LOG_FILE"
echo ""

# Start in background with logging
nohup $PYTHON_CMD -m ha_gateway.server --config "$CONFIG_FILE" > "$LOG_FILE" 2>&1 &
GATEWAY_PID=$!

echo "Gateway started with PID: $GATEWAY_PID"
echo "To stop: kill $GATEWAY_PID"
echo "To view logs: tail -f $LOG_FILE"

# Wait a moment for startup
sleep 2

# Check if process is running
if kill -0 $GATEWAY_PID 2>/dev/null; then
    echo "Gateway is running successfully"
    echo "WebSocket endpoint: ws://localhost:8124/ws"
else
    echo "Failed to start gateway"
    echo "Check logs: tail -f $LOG_FILE"
    exit 1
fi