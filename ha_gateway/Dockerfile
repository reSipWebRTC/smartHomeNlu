FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create config directory
RUN mkdir -p /config

# Expose port
EXPOSE 8124

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import aiohttp; import asyncio; import sys; \
    async def check(): \
        try: \
            async with aiohttp.ClientSession() as session: \
                async with session.get('http://localhost:8124/health') as resp: \
                    return resp.status == 200 \
        except: \
            return False \
    sys.exit(0 if asyncio.run(check()) else 1)" || exit 1

# Run the gateway
CMD ["python", "-m", "ha_gateway.server", "--config", "/config/config.yaml"]