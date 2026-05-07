#!/usr/bin/env python3

import re


def test_parse_dependency(dependency_str, current_resource_group="bicep-template"):
    try:
        # Handle format() function with subnet references
        if "format(" in dependency_str and "/subnets/" in dependency_str:
            subnet_match = re.search(r'/subnets/([^\'",}]+)', dependency_str)
            if subnet_match:
                subnet_name = subnet_match.group(1)
                return subnet_name, "Microsoft.Network/virtualNetworks/subnets", current_resource_group

        # Handle resourceId function format
        if "resourceId(" in dependency_str:
            match = re.search(r"resourceId\([^)]+\)", dependency_str)
            if match:
                resource_id_call = match.group(0)

                arg_pattern = r"'([^']+)'|variables\('([^']+)'\)|parameters\('([^']+)'\)"
                args = re.findall(arg_pattern, resource_id_call)

                parsed_args = []
                for groups in args:
                    for group in groups:
                        if group:
                            parsed_args.append(group)

                if len(parsed_args) >= 2:
                    dependency_type = parsed_args[0]
                    dependency_name = parsed_args[1]
                    dependency_rg = current_resource_group

                    return dependency_name, dependency_type, dependency_rg
    except Exception as e:
        print(f"Error: {e}")
        return "unknown", "Unknown", current_resource_group


# Test cases including the problematic format() case
test_cases = [
    "[format('{0}/subnets/WebAppSubnet', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')))]",
    "[resourceId('Microsoft.Sql/servers/databases', variables('sqlServerName'), variables('sqlDatabaseName'))]",
    "[resourceId('Microsoft.Network/virtualNetworks', variables('vnetName'))]",
    "[resourceId('Microsoft.Storage/storageAccounts', variables('storageAccountName'))]",
]

for test in test_cases:
    print(f"Testing: {test}")
    result = test_parse_dependency(test)
    print(f"Result: {result}")
    print()
