#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CloudHorus - Azure Cloud Architecture Guardian

CloudHorus soars above your Azure cloud infrastructure with the all-seeing eye of Horus.
Guardian of cloud architectures, protector of infrastructure integrity.
Navigate your cloud kingdom with divine clarity and falcon-sharp precision.

Soar Above Your Cloud Complexity
All-Seeing Eye of Your Azure Sky
"""

import argparse
import json
import os
import sys
from typing import List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cloudhorus.exporters import DOTExporter, DrawioExporter, PNGExporter  # noqa: E402
from cloudhorus.models.configuration import LayoutConfig, VisualizationConfig  # noqa: E402
from cloudhorus.services import (  # noqa: E402
    AzureNetworkService,
    AzureResourceService,
    BicepProcessorService,
    BicepService,
    GraphBuilderService,
    GraphGeneratorService,
    ResourceAnalysisService,
    SubnetResolverService,
    TemplateRegistryService,
)
from utils.logger import SingletonLogger  # noqa: E402
from utils.windows_encoding import setup_windows_console  # noqa: E402

# Setup Windows console encoding
setup_windows_console()

logger = SingletonLogger().get_logger()


def str_to_bool(value: str) -> bool:
    """Convert string representation to boolean value.

    Args:
        value: String representation of a boolean ('true', 'false', etc.)

    Returns:
        Corresponding boolean value
    """
    return value.lower() in ("true", "yes", "1", "t", "y")


def parse_arguments() -> argparse.Namespace:
    """Parse and validate command line arguments.

    Returns:
        Namespace object containing validated arguments
    """
    parser = argparse.ArgumentParser(
        description="CloudHorus - Guardian of Azure cloud architecture with the all-seeing eye of Horus. "
        + "Soar above your cloud complexity and survey your infrastructure kingdom with divine clarity. "
        + "Two flight modes: Live mode (scan active Azure territories) and Template mode (analyze architectural blueprints). "
        + "Template mode automatically activated when --bicepFiles provided.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--subscriptions",
        nargs="+",
        required=False,
        help="Azure subscription territories to survey. Required for Live mode. NOT ALLOWED in Template mode (uses defaults).",
    )

    parser.add_argument(
        "--resourcegroups",
        nargs="+",
        required=False,
        help="Azure resource group domains to scan. Required for Live mode. NOT ALLOWED in Template mode (uses defaults).",
    )

    parser.add_argument(
        "--tenants",
        nargs="+",
        required=False,
        help="Azure tenant realms under Horus protection. Required for Live mode. NOT ALLOWED in Template mode (uses defaults).",
    )

    parser.add_argument(
        "--subnetOptimization",
        nargs="+",
        default=None,
        help="Optimize subnet display in diagram per subscription. "
        + "Provide one boolean value (true/false) for each subscription in the same order as --subscriptions. "
        + "If not provided, defaults to False for all subscriptions.",
    )

    parser.add_argument(
        "--edgeDirection",
        type=str,
        choices=["TB", "BT", "LR", "RL"],
        default="TB",
        help="Horus flight pattern direction (TB=Top-Bottom, BT=Bottom-Top, LR=Left-Right, RL=Right-Left)",
    )

    parser.add_argument(
        "--tenantDirection", type=str, choices=["TB", "LR"], default="LR", help="Tenant realm surveillance pattern"
    )

    parser.add_argument(
        "--maxSubnetPerline", type=int, default=4, help="Maximum number of subnets to display per line within a VNet"
    )

    parser.add_argument(
        "--rankDebug", type=str, default="False", help="Reveal hidden architectural elements for divine inspection"
    )

    parser.add_argument(
        "--peOptimization",
        nargs="+",
        default=None,
        help="Optimize Private Endpoints display in subnet per subscription. "
        + "Provide one boolean value (true/false) for each subscription in the same order as --subscriptions. "
        + "If not provided, defaults to True for all subscriptions.",
    )

    parser.add_argument(
        "--resourcesEdgeLength", nargs="+", default="1", help="Divine sight distance for resource surveillance"
    )

    parser.add_argument(
        "--resourceGroupsEdgeLengthListBySubscription",
        nargs="+",
        default=None,
        help="Falcon sight range for resource group territories per subscription domain",
    )

    parser.add_argument(
        "--privateDnsZonesOptimization",
        type=str,
        default="True",
        help="Optimize Private DNS Zones in the visualization for cleaner diagrams",
    )

    parser.add_argument(
        "--crossPeOptimization",
        nargs="+",
        default=None,
        help="Optimize Private Endpoints display in cross resource group dependencies per subscription. "
        + "Provide one boolean value (true/false) for each subscription in the same order as --subscriptions. "
        + "If not provided, defaults to False for all subscriptions.",
    )

    # Bicep template support arguments
    parser.add_argument(
        "--bicepFiles",
        nargs="+",
        default=None,
        help=(
            "List of paths to Bicep template files. Can be a single file or multiple"
            " files for multi-environment deployments. When provided, automatically"
            " enables Bicep mode."
        ),
    )

    parser.add_argument(
        "--parametersFiles",
        nargs="+",
        default=None,
        help="List of paths to parameters files. Must match the order and number of --bicepFiles.",
    )

    parser.add_argument(
        "--discoverResourceGroups",
        nargs="*",
        default=None,
        help="Divine discovery mode: List of resource group names for which dependency discovery should be enabled. "
        "Only the specified RGs will trigger discovery of related resource groups through dependencies "
        "(e.g., VNet integrations, Private Endpoints, cross-RG dependencies). "
        "If provided without values (flag only), discovery is enabled for ALL resource groups. "
        "Example: --discoverResourceGroups rg-hub-01 rg-app-01",
    )

    parser.add_argument(
        "--exportDrawio",
        type=str,
        default="False",
        help="Export graph to Draw.io XML format (.drawio file) in addition to PNG. "
        "When enabled, CloudHorus will generate a .drawio file that can be imported into Draw.io "
        "for further editing and customization. This allows you to refine your architecture diagrams "
        "with Draw.io's powerful editing capabilities.",
    )

    parser.add_argument(
        "--authMethod",
        type=str,
        choices=["device-code", "service-principal", "environment"],
        default="device-code",
        help="Authentication method. "
        "'device-code' uses interactive browser login. "
        "'service-principal' reads AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET env vars. "
        "'environment' uses DefaultAzureCredential to auto-detect pre-existing auth "
        "(managed identity, az login, env vars) — ideal for CI/CD runners where "
        "authentication is already done before CloudHorus runs.",
    )

    parser.add_argument(
        "--nonInteractive",
        type=str,
        default="False",
        help="Enable non-interactive / CI-CD mode. When true, CloudHorus will never prompt "
        "for user input and will fail-fast with exit code 1 if interactive auth would be needed. "
        "Automatically enabled when --authMethod is 'service-principal' or 'environment'. "
        "Can also be set via CLOUDHORUS_NON_INTERACTIVE=true environment variable.",
    )

    return parser.parse_args()


def print_banner() -> None:
    """Print CloudHorus banner with Windows Unicode fallback."""
    try:
        # Try Unicode banner first
        print("""
╔═════════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                         ║
║     ██████╗██╗      ██████╗ ██╗   ██╗██████╗ ██╗  ██╗ ██████╗ ██████╗ ██╗   ██╗███████╗ ║
║    ██╔════╝██║     ██╔═══██╗██║   ██║██╔══██╗██║  ██║██╔═══██╗██╔══██╗██║   ██║██╔════╝ ║
║    ██║     ██║     ██║   ██║██║   ██║██║  ██║███████║██║   ██║██████╔╝██║   ██║███████╗ ║
║    ██║     ██║     ██║   ██║██║   ██║██║  ██║██╔══██║██║   ██║██╔══██╗██║   ██║╚════██║ ║
║    ╚██████╗███████╗╚██████╔╝╚██████╔╝██████╔╝██║  ██║╚██████╔╝██║  ██║╚██████╔╝███████║ ║
║     ╚═════╝╚══════╝ ╚═════╝  ╚═════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝ ║
║                                                                                         ║
║                      Azure Cloud Architecture Guardian                                 ║
║                            All-Seeing Eye of Horus                                     ║
║                         Soar Above Your Cloud Complexity                               ║
║                                                                                         ║
║ ─────────────────────────────── DIVINE POWERS ─────────────────────────────────────────║
║   Live Mode         │ Survey active Azure territories with falcon precision             ║
║   Template Mode     │ Analyze architectural blueprints with divine wisdom               ║
║   Multi-Realm       │ Comprehensive analysis across subscription kingdoms               ║
║   Guardian Watch    │ Protect infrastructure integrity with eternal vigilance           ║
║                                                                                         ║
║ ────────────────────────────── DIVINE CREATION ────────────────────────────────────────║
║   Author: Hicham Fellah                                                                ║
║   GitHub: https://github.com/FELLAH-tech                                               ║
║   Documentation: https://github.com/FELLAH-tech/CloudHorus/tree/main/docs              ║
║   Star the Repository: https://github.com/FELLAH-tech/CloudHorus                       ║
║                                                                                         ║
║ ─────────────────────────────── BLESSED FOR THE CLOUD ────────────────────────────────║
║   Optimized for Enterprise Cloud Infrastructure                                        ║
║   Enterprise-Grade Cloud Architecture Visualization                                    ║
║   Advanced Dependency Mapping & Resource Discovery                                     ║
║                                                                                         ║
╚═════════════════════════════════════════════════════════════════════════════════════════╝
""")
    except UnicodeEncodeError:
        # Fallback to ASCII-only banner for Windows console compatibility
        print("""
+=====================================================================================+
|                                                                                     |
|      #####  #        ####  #    # ##### #    # ####  ####  #    #  #####          |
|     #       #       #    # #    # #     #    # #   # #   # #    # #              |
|     #       #       #    # #    # #     ##  ## #   # #   # #    #  #####         |
|     #       #       #    # #    # #     # ## # #   # #   # #    #       #        |
|     #       #       #    # #    # #     #    # #   # #   # #    # #     #        |
|      #####  #######  ####   ####  ##### #    # ####  ####   ####   #####         |
|                                                                                     |
|                    * Azure Cloud Architecture Guardian *                           |
|                        * All-Seeing Eye of Horus *                                |
|                     * Soar Above Your Cloud Complexity *                          |
|                                                                                     |
| -------------------------------- DIVINE POWERS ----------------------------------- |
|   * Live Mode      | Survey active Azure territories with falcon precision        |
|   * Template Mode  | Analyze architectural blueprints with divine wisdom          |
|   * Multi-Realm    | Comprehensive analysis across subscription kingdoms          |
|   * Guardian Watch | Protect infrastructure integrity with eternal vigilance      |
|                                                                                     |
| ------------------------------- DIVINE CREATION --------------------------------- |
|   * Author: Hicham Fellah                                                          |
|   * GitHub: https://github.com/FELLAH-tech                                         |
|   * Documentation: https://github.com/FELLAH-tech/CloudHorus/tree/main/docs       |
|   * Star the Repository: https://github.com/FELLAH-tech/CloudHorus                 |
|                                                                                     |
| ----------------------------- BLESSED FOR THE CLOUD ------------------------------ |
|   * Optimized for Enterprise Cloud Infrastructure                                  |
|   * Enterprise-Grade Cloud Architecture Visualization                              |
|   * Advanced Dependency Mapping & Resource Discovery                               |
|                                                                                     |
+=====================================================================================+
""")


def main() -> None:
    """CloudHorus main entry point - Awaken the guardian of cloud architecture."""

    import time

    args = parse_arguments()

    # ── Determine non-interactive mode (CI/CD) ──
    non_interactive = (
        str_to_bool(args.nonInteractive)
        or str_to_bool(os.environ.get("CLOUDHORUS_NON_INTERACTIVE", "false"))
        or args.authMethod in ("service-principal", "environment")
    )
    if non_interactive:
        os.environ["CLOUDHORUS_NON_INTERACTIVE"] = "true"

    # Display CloudHorus Divine Banner (skip in CI/CD)
    if not non_interactive and not sys.platform.startswith("win"):
        print_banner()

    logger.info("CloudHorus Divine Systems Online - Guardian Awakened")
    logger.info("Initializing all-seeing surveillance capabilities...")

    if not non_interactive:
        time.sleep(1)

    # ── Auth method: set env var BEFORE any Azure module is imported ──
    if args.authMethod == "service-principal":
        os.environ["CLOUDHORUS_AUTH_METHOD"] = "service-principal"
        # Validate required env vars early
        missing = []
        if not os.environ.get("AZURE_CLIENT_ID"):
            missing.append("AZURE_CLIENT_ID")
        if not os.environ.get("AZURE_TENANT_ID"):
            missing.append("AZURE_TENANT_ID")
        if not os.environ.get("AZURE_CLIENT_SECRET"):
            missing.append("AZURE_CLIENT_SECRET")
        if missing:
            logger.error(f"Service-principal auth requires these environment variables: {', '.join(missing)}")
            exit(1)
        logger.info("🔐 CloudHorus: Service Principal authentication mode selected")
    elif args.authMethod == "environment":
        os.environ["CLOUDHORUS_AUTH_METHOD"] = "environment"
        logger.info(
            "🔐 CloudHorus: Environment authentication mode selected "
            "(auto-detecting: env vars → managed identity → az login → PowerShell)"
        )
    else:
        os.environ.setdefault("CLOUDHORUS_AUTH_METHOD", "device-code")

    # Convert string arguments to appropriate types
    rank_debug = str_to_bool(args.rankDebug)
    privateDnsZonesOptimization = str_to_bool(args.privateDnsZonesOptimization)
    # discoverResourceGroups: None=disabled, []=all RGs, ['rg1','rg2']=specific RGs
    if args.discoverResourceGroups is None:
        discoverResourceGroups = []  # disabled
    elif len(args.discoverResourceGroups) == 0:
        discoverResourceGroups = list(args.resourcegroups)  # all RGs
    else:
        discoverResourceGroups = args.discoverResourceGroups  # specific RGs
    exportDrawio = str_to_bool(args.exportDrawio)

    # Auto-detect Template mode
    use_local_template = bool(args.bicepFiles)

    if use_local_template:
        logger.info("CloudHorus: Template mode detected - analyzing architectural blueprints")

        # Validate Bicep files and parameters
        if not args.parametersFiles:
            logger.error("CloudHorus Error: --parametersFiles required when examining --bicepFiles blueprints")
            exit(1)

        if len(args.bicepFiles) != len(args.parametersFiles):
            logger.error(
                f"CloudHorus Error: Blueprint count ({len(args.bicepFiles)}) must match parameters count ({len(args.parametersFiles)})"
            )
            exit(1)

        # Validate all files exist
        for i, (bicep_file, params_file) in enumerate(zip(args.bicepFiles, args.parametersFiles)):
            if not os.path.exists(bicep_file):
                logger.error(f"CloudHorus Error: Blueprint {i+1} not found in realm: {bicep_file}")
                exit(1)

            if not os.path.exists(params_file):
                logger.error(f"CloudHorus Error: Parameters scroll {i+1} missing: {params_file}")
                exit(1)

        logger.info(f"CloudHorus: Divine sight locked onto {len(args.bicepFiles)} architectural blueprint(s)")
        for i, (bicep_file, params_file) in enumerate(zip(args.bicepFiles, args.parametersFiles)):
            logger.info(f"  Blueprint {i+1}: {bicep_file} with parameters {params_file}")

        # Check if user provided subscription/tenant/resourcegroup arguments in Template mode
        if args.subscriptions is not None:
            logger.error("CloudHorus Error: --subscriptions not allowed in Template mode.")
            exit(1)

        if args.tenants is not None:
            logger.error("CloudHorus Error: --tenants not allowed in Template mode.")
            exit(1)

        if args.resourcegroups is not None:
            logger.error("CloudHorus Error: --resourcegroups not allowed in Template mode.")
            exit(1)

        # Derive tenant / subscription / resource-group per template.
        # Each parameters file may contain an optional "_cloudHorus" metadata
        # block that declares the Azure scope for that template:
        #   "_cloudHorus": {
        #       "tenant": "<tenant-id>",
        #       "subscription": "<subscription-id>",
        #       "resourceGroup": "<rg-name>"
        #   }
        # When present the values override the synthetic defaults, enabling
        # cross-tenant and cross-subscription Bicep scenarios.
        num_templates = len(args.bicepFiles)
        args.subscriptions = []
        args.tenants = []
        args.resourcegroups = []

        has_custom_metadata = False
        for i, params_file in enumerate(args.parametersFiles):
            try:
                with open(params_file, "r") as f:
                    params_data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not read parameters file {params_file} for metadata: {e}")
                params_data = {}

            meta = params_data.get("_cloudHorus", {})
            tenant = meta.get("tenant", "cloudhorus-tenant")
            subscription = meta.get("subscription", "cloudhorus-subscription")
            resource_group = meta.get("resourceGroup", f"cloudhorus-rg-{i+1}")

            if meta:
                has_custom_metadata = True

            args.tenants.append(tenant)
            args.subscriptions.append(subscription)
            args.resourcegroups.append(resource_group)

        if has_custom_metadata:
            logger.info(f"CloudHorus: Custom scope metadata detected in parameters files")

        unique_tenants = list(dict.fromkeys(args.tenants))  # preserve order, deduplicate
        unique_subs = list(dict.fromkeys(args.subscriptions))
        logger.info(f"CloudHorus: Divine realm configured for {num_templates} blueprint(s)")
        logger.info(f"  Tenants ({len(unique_tenants)}): {', '.join(unique_tenants)}")
        logger.info(f"  Subscriptions ({len(unique_subs)}): {', '.join(unique_subs)}")
        logger.info(f"  Resource groups: {', '.join(args.resourcegroups)}")

    else:
        # Live mode - validate required arguments
        if not args.subscriptions or not args.tenants or not args.resourcegroups:
            logger.error("CloudHorus Error: Live mode requires --subscriptions, --tenants, and --resourcegroups.")
            exit(1)
        logger.info("CloudHorus: Live mode detected - surveying active Azure territories")
        logger.info(f"Divine sight range: {len(args.subscriptions)} subscription realm(s)")

    # Handle optimization flags per subscription
    pe_optimization = _parse_per_subscription_flag(args.peOptimization, len(args.subscriptions), True, "peOptimization")
    crossPeOptimization = _parse_per_subscription_flag(
        args.crossPeOptimization, len(args.subscriptions), False, "crossPeOptimization"
    )
    subnet_optimization = _parse_per_subscription_flag(
        args.subnetOptimization, len(args.subscriptions), False, "subnetOptimization"
    )

    # Set resource group edge lengths
    if args.resourceGroupsEdgeLengthListBySubscription is None:
        resourceGroupsEdgeLengthList = [4] * len(args.subscriptions)
    else:
        resourceGroupsEdgeLengthList = [int(x) for x in args.resourceGroupsEdgeLengthListBySubscription]
        if len(resourceGroupsEdgeLengthList) != len(args.subscriptions):
            logger.error(
                "CloudHorus Error: resourceGroupsEdgeLengthListBySubscription count must match subscription count."
            )
            exit(1)

    # Create optimization configs per subscription
    optimizations = []
    for i in range(len(args.subscriptions)):
        from cloudhorus.models.configuration import OptimizationConfig

        opt = OptimizationConfig(
            subnet_optimization=subnet_optimization[i],
            pe_optimization=pe_optimization[i],
            cross_pe_optimization=crossPeOptimization[i],
            private_dns_zones_optimization=privateDnsZonesOptimization,
        )
        optimizations.append(opt)

    # Create visualization configuration
    from cloudhorus.models.configuration import Direction, RankDebugMode

    # Convert direction strings to enums
    edge_dir = Direction.TOP_TO_BOTTOM
    if args.edgeDirection == "TB":
        edge_dir = Direction.TOP_TO_BOTTOM
    elif args.edgeDirection == "BT":
        edge_dir = Direction.BOTTOM_TO_TOP
    elif args.edgeDirection == "LR":
        edge_dir = Direction.LEFT_TO_RIGHT
    elif args.edgeDirection == "RL":
        edge_dir = Direction.RIGHT_TO_LEFT

    tenant_dir = Direction.LEFT_TO_RIGHT if args.tenantDirection == "LR" else Direction.TOP_TO_BOTTOM
    rank_mode = RankDebugMode.VISIBLE if rank_debug else RankDebugMode.INVISIBLE

    # Parse resources edge length
    res_edge_len = (
        int(args.resourcesEdgeLength[0])
        if isinstance(args.resourcesEdgeLength, list)
        else int(args.resourcesEdgeLength)
    )

    layout_config = LayoutConfig(
        edge_direction=edge_dir,
        tenant_direction=tenant_dir,
        max_subnet_per_line=args.maxSubnetPerline,
        resources_edge_length=res_edge_len,
        resource_groups_edge_length=4,  # Default, will be per-subscription in config
        rank_debug=rank_mode,
    )

    config = VisualizationConfig(
        tenants=args.tenants,
        subscriptions=args.subscriptions,
        resource_groups=args.resourcegroups,
        optimizations=optimizations,
        layout=layout_config,
        rg_edge_lengths=resourceGroupsEdgeLengthList,
        discover_resource_groups=discoverResourceGroups,
        export_drawio=exportDrawio,
        use_local_template=use_local_template,
        bicep_files=args.bicepFiles if use_local_template else None,
        parameters_files=args.parametersFiles if use_local_template else None,
    )

    # Initialize services with dependency injection
    # First, create Azure credential if in live mode using original AzureUtility
    if not use_local_template:
        from core.azure_cli import az_sdk as azure_utility

        try:
            credential = azure_utility._get_credential()
            logger.info("Azure credentials initialized successfully using original authentication chain")
        except Exception as e:
            logger.error(f"Failed to initialize Azure credentials: {e}")
            logger.error("Please run 'az login' or configure Azure authentication")
            exit(1)
    else:
        # Template mode: Create a minimal credential object (won't be used)
        credential = None
        azure_utility = None

    # Create services - in template mode, some services won't be used
    # but we still instantiate them with None credential (they'll handle it)
    from cloudhorus.services.azure_auth_service import AzureAuthService

    _auth_service = AzureAuthService() if not use_local_template else None  # noqa: F841

    # These services work in both modes
    template_registry_service = TemplateRegistryService()
    bicep_service = BicepService()
    bicep_processor_service = BicepProcessorService()
    _subnet_resolver_service = SubnetResolverService()  # noqa: F841
    resource_analysis_service = ResourceAnalysisService()
    graph_builder_service = GraphBuilderService()

    # Azure services only needed in live mode
    if not use_local_template:
        azure_resource_service = AzureResourceService(credential)
        azure_network_service = AzureNetworkService(credential=credential, template_registry=template_registry_service)
    else:
        # Template mode doesn't need real Azure clients
        azure_resource_service = None
        azure_network_service = None

    # Initialize generator service
    generator_service = GraphGeneratorService(
        config=config,
        azure_resource_service=azure_resource_service,
        template_registry=template_registry_service,
        network_service=azure_network_service,
        bicep_service=bicep_service,
        bicep_processor=bicep_processor_service,
        analysis_service=resource_analysis_service,
        graph_builder=graph_builder_service,
    )

    # Initialize exporters
    _png_exporter = PNGExporter()  # noqa: F841
    _dot_exporter = DOTExporter()  # noqa: F841
    _drawio_exporter = DrawioExporter() if exportDrawio else None  # noqa: F841

    # Validate services
    if not generator_service.validate():
        logger.error("CloudHorus Error: Service validation failed")
        exit(1)

    # Generate graph
    if discoverResourceGroups:
        logger.info(f"🦅 CloudHorus: Divine Discovery Mode ENABLED for: {discoverResourceGroups}")

    logger.info("CloudHorus: Taking flight - commencing divine surveillance of cloud architecture...")

    # Generate graph - this returns the PNG path (old service behavior)
    png_path = generator_service.generate_graph(
        tenants=config.tenants,
        subscriptions=config.subscriptions,
        resource_groups=config.resource_groups,
        use_bicep_templates=config.use_local_template,
        bicep_files=config.bicep_files,
        parameters_files=config.parameters_files,
    )

    if png_path is None:
        logger.error("CloudHorus Error: Graph generation failed")
        exit(1)

    logger.info(f"✅ CloudHorus completed successfully: {png_path}")
    logger.info("CloudHorus: Divine surveillance complete - cloud architecture mapped")


def _parse_per_subscription_flag(
    flag_value: Optional[List[str]], num_subscriptions: int, default: bool, flag_name: str
) -> List[bool]:
    """Parse per-subscription boolean flag.

    Args:
        flag_value: User-provided flag values
        num_subscriptions: Number of subscriptions
        default: Default value if not provided
        flag_name: Name of the flag for error messages

    Returns:
        List of boolean values, one per subscription
    """
    if flag_value is None:
        return [default] * num_subscriptions

    result = [str_to_bool(val) for val in flag_value]

    if len(result) != num_subscriptions:
        logger.error(f"CloudHorus Error: {flag_name} count must match subscription realm count.")
        exit(1)

    return result


if __name__ == "__main__":
    main()
