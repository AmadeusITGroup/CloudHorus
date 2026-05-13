SKIP_RESOURCE_PATTERNS = [
    r"Microsoft.Network/networkSecurityGroups/.*",
    r"Microsoft.Network/routeTables/.*",
    r"microsoft.insights/scheduledqueryrules.*",
    r"Microsoft.Insights/metricAlerts.*",
    r"Microsoft.Network/privateDnsZones",
    r"Microsoft.Network/bastionHosts",
    r"microsoft.alertsmanagement/smartdetectoralertrules",
    r".*Microsoft.Resources/deploymentScripts.*",
]

SKIP_DEPENDENCY_RESOURCE_PATTERNS = [
    r"Microsoft.Network/networkSecurityGroups/.*",
    r"Microsoft.Network/routeTables/.*",
    r"Microsoft.Network/virtualNetworks$",
    r"microsoft.insights/scheduledqueryrules.*",
    r"Microsoft.Insights/metricAlerts.*",
    r"Microsoft.Network/privateDnsZones",
    r"Microsoft.Network/bastionHosts",
    r"microsoft.alertsmanagement/smartdetectoralertrules",
    r".*Microsoft.Resources/deploymentScripts.*",
]
