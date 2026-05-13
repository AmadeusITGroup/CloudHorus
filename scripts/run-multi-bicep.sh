#!/bin/bash

# Multi-Bicep Template Visualization Script
# This script provides easy commands to visualize the multi-environment Bicep templates

echo "🚀 Azure Multi-Environment Bicep Visualizer"
echo "============================================="

# Function to run multi-environment visualization
run_multi_environment() {
    echo "📊 Generating multi-environment diagram (dev + staging + production)..."
    
    python3 src/main.py \
        --useLocalTemplate True \
        --bicepFiles \
            "multi-bicep-templates/environments/development/main.bicep" \
            "multi-bicep-templates/environments/staging/main.bicep" \
            "multi-bicep-templates/environments/production/main.bicep" \
        --parametersFiles \
            "multi-bicep-templates/environments/development/main.parameters.json" \
            "multi-bicep-templates/environments/staging/main.parameters.json" \
            "multi-bicep-templates/environments/production/main.parameters.json" \
        --subscriptions \
            "11111111-1111-1111-1111-111111111111" \
            "22222222-2222-2222-2222-222222222222" \
            "33333333-3333-3333-3333-333333333333" \
        --tenants \
            "dev-tenant-id" \
            "staging-tenant-id" \
            "prod-tenant-id" \
        --resourcegroups \
            "dev-rg-main,dev-rg-network,dev-rg-storage" \
            "stg-rg-main,stg-rg-network,stg-rg-storage,stg-rg-shared" \
            "prod-rg-main,prod-rg-network,prod-rg-storage,prod-rg-shared,prod-rg-network-dr,prod-rg-storage-dr" \
        --edgeDirection TB \
        --subnetOptimization True True True \
        --peOptimization True True True \
        --privateDnsZonesOptimization True \
        --crossPeOptimization True True True
}

# Function to run development environment only
run_development() {
    echo "🔧 Generating development environment diagram..."
    
    python3 src/main.py \
        --useLocalTemplate True \
        --bicepFile "multi-bicep-templates/environments/development/main.bicep" \
        --parametersFile "multi-bicep-templates/environments/development/main.parameters.json" \
        --subscriptions "11111111-1111-1111-1111-111111111111" \
        --tenants "dev-tenant-id" \
        --resourcegroups "dev-rg-main,dev-rg-network,dev-rg-storage" \
        --edgeDirection TB \
        --subnetOptimization True \
        --peOptimization True \
        --privateDnsZonesOptimization True
}

# Function to run staging environment only
run_staging() {
    echo "🧪 Generating staging environment diagram..."
    
    python3 src/main.py \
        --useLocalTemplate True \
        --bicepFile "multi-bicep-templates/environments/staging/main.bicep" \
        --parametersFile "multi-bicep-templates/environments/staging/main.parameters.json" \
        --subscriptions "22222222-2222-2222-2222-222222222222" \
        --tenants "staging-tenant-id" \
        --resourcegroups "stg-rg-main,stg-rg-network,stg-rg-storage,stg-rg-shared" \
        --edgeDirection TB \
        --subnetOptimization True \
        --peOptimization True \
        --privateDnsZonesOptimization True \
        --crossPeOptimization True
}

# Function to run production environment only
run_production() {
    echo "🏭 Generating production environment diagram..."
    
    python3 src/main.py \
        --useLocalTemplate True \
        --bicepFile "multi-bicep-templates/environments/production/main.bicep" \
        --parametersFile "multi-bicep-templates/environments/production/main.parameters.json" \
        --subscriptions "33333333-3333-3333-3333-333333333333" \
        --tenants "prod-tenant-id" \
        --resourcegroups "prod-rg-main,prod-rg-network,prod-rg-storage,prod-rg-shared,prod-rg-network-dr,prod-rg-storage-dr" \
        --edgeDirection TB \
        --subnetOptimization True \
        --peOptimization True \
        --privateDnsZonesOptimization True \
        --crossPeOptimization True
}

# Main menu
case "$1" in
    "all" | "multi")
        run_multi_environment
        ;;
    "dev" | "development")
        run_development
        ;;
    "stg" | "staging")
        run_staging
        ;;
    "prod" | "production")
        run_production
        ;;
    *)
        echo "Usage: $0 {all|dev|stg|prod}"
        echo ""
        echo "Commands:"
        echo "  all, multi    - Generate diagram with all environments (dev + staging + production)"
        echo "  dev           - Generate development environment diagram only"
        echo "  stg           - Generate staging environment diagram only"
        echo "  prod          - Generate production environment diagram only"
        echo ""
        echo "Examples:"
        echo "  $0 all        # Generate complete multi-environment diagram"
        echo "  $0 dev        # Generate development environment only"
        echo "  $0 prod       # Generate production environment with DR"
        echo ""
        echo "Output: azure_resources.png will be generated in the current directory"
        exit 1
        ;;
esac

echo ""
echo "✅ Visualization complete! Check azure_resources.png"
echo "🔍 The generated diagram shows:"
echo "   • Cross-resource group dependencies"
echo "   • Network topology with subnets"
echo "   • Private endpoints and DNS zones"
echo "   • Multi-region setup (production)"
echo "   • Modular Bicep architecture"
