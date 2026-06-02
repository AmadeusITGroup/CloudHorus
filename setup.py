#!/usr/bin/env python3
"""
CloudHorus Setup Script

This setup script allows users to install CloudHorus as a Python package.
It handles dependencies, entry points, and package metadata.

NOTE: pyproject.toml is the primary packaging config.
This file is kept for backward compatibility with older pip versions.
"""

import os
import re

from setuptools import find_packages, setup

# Read the version from version.py
try:
    with open(os.path.join("src", "version.py"), "r") as f:
        version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", f.read(), re.M)
        version = version_match.group(1) if version_match else "2.0.0"
except FileNotFoundError:
    version = "2.0.0"

# Read the long description from README.md
with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

# Core dependencies required for basic functionality
INSTALL_REQUIRES = [
    "graphviz>=0.20",
    "tqdm>=4.65.0",
    "colorama>=0.4.6",
    "Pillow>=9.0.0",
    "python-hcl2>=8.1.0",
    "pywebview>=5.0",
]

# Azure SDK dependencies for direct Azure API access
AZURE_REQUIRES = [
    "azure-identity>=1.15.0",
    "azure-mgmt-resource>=23.0.0",
    "azure-mgmt-network>=23.0.0",
    "azure-mgmt-subscription>=3.0.0",
    "azure-core>=1.28.0",
]

# Export format dependencies
EXPORT_REQUIRES = [
    "graphviz2drawio>=1.1.0",
]

# Development dependencies
DEV_REQUIRES = [
    "pytest>=7.0.0",
    "pytest-cov>=4.1.0",
    "black>=23.3.0",
    "isort>=5.12.0",
    "mypy>=1.3.0",
]

setup(
    name="cloudhorus",
    version=version,
    author="Hicham Fellah",
    author_email="",
    description="Azure Cloud Architecture Visualizer — Soar above your cloud complexity",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/CloudHorus/CloudHorus",
    project_urls={
        "Bug Tracker": "https://github.com/CloudHorus/CloudHorus/issues",
        "Documentation": "https://github.com/CloudHorus/CloudHorus#readme",
        "Source Code": "https://github.com/CloudHorus/CloudHorus",
    },
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    include_package_data=True,
    package_data={
        "": ["icons/*.png"],
    },
    python_requires=">=3.10",
    install_requires=INSTALL_REQUIRES,
    extras_require={
        "azure": AZURE_REQUIRES,
        "export": EXPORT_REQUIRES,
        "dev": DEV_REQUIRES,
        "all": AZURE_REQUIRES + EXPORT_REQUIRES + DEV_REQUIRES,
    },
    entry_points={
        "console_scripts": [
            "cloudhorus=main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Visualization",
        "Topic :: System :: Systems Administration",
        "Operating System :: OS Independent",
    ],
    keywords="azure, visualization, graph, diagram, resources, architecture, cloud, infrastructure",
)
