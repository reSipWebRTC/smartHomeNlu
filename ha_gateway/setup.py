#!/usr/bin/env python3
"""Setup script for Home Assistant Gateway."""

from setuptools import setup, find_packages

setup(
    name="ha_gateway",
    version="0.1.0",
    description="A standalone Home Assistant bridge",
    packages=find_packages(),
    install_requires=[
        "aiohttp>=3.8.0",
        "pyyaml>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "ha-gateway=run_server:main",
        ],
    },
    python_requires=">=3.8",
)