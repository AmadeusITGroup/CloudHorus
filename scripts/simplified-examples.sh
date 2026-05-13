#!/bin/bash

# CloudHorus - Simplified Bicep Mode Examples
# This script shows how to use the streamlined Bicep mode

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "==================================="
echo "CloudHorus — Bicep Mode Examples"
echo "==================================="
echo

cd "$PROJECT_ROOT"

echo "1. Single Bicep Template (Development)"
echo "Command: python3 src/main.py --bicepFiles multi-bicep-templates/environments/development/main.bicep --parametersFiles multi-bicep-templates/environments/development/main.parameters.json"
echo "Note: Automatically detects Bicep mode, uses defaults: bicep-subscription, bicep-tenant, bicep-rg-1"
echo

echo "2. Multiple Bicep Templates (All Environments)"  
echo "Command: python3 src/main.py --bicepFiles multi-bicep-templates/environments/development/main.bicep multi-bicep-templates/environments/staging/main.bicep multi-bicep-templates/environments/production/main.bicep --parametersFiles multi-bicep-templates/environments/development/main.parameters.json multi-bicep-templates/environments/staging/main.parameters.json multi-bicep-templates/environments/production/main.parameters.json"
echo "Note: Auto-generates resource groups: bicep-rg-1, bicep-rg-2, bicep-rg-3"
echo

echo "3. Bicep Mode with Custom Resource Groups"
echo "Command: python3 src/main.py --bicepFiles multi-bicep-templates/environments/development/main.bicep --parametersFiles multi-bicep-templates/environments/development/main.parameters.json --resourcegroups my-dev-rg"
echo "Note: Overrides default resource group naming"
echo

echo "4. Azure Mode (Live Resources)"
echo "Command: python3 src/main.py --subscriptions <sub-id> --tenants <tenant-id> --resourcegroups <rg-name>"
echo "Note: Exports from live Azure resources"
echo

echo "==================================="
echo "Key Improvements:"
echo "- Removed --useLocalTemplate (auto-detected)"
echo "- Removed --bicepFile (use --bicepFiles for both single/multiple)"
echo "- Auto-generates sensible defaults for subscriptions/tenants/RGs"
echo "- Cleaner, more intuitive interface"
echo "==================================="
