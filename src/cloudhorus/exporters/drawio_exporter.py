"""Draw.io Exporter for converting graphs to Draw.io XML format."""

import os
from typing import Optional

from graphviz import Digraph

from cloudhorus.services.base import BaseService


class DrawioExporter(BaseService):
    """Exporter for Draw.io XML format.

    This exporter converts Graphviz graphs to Draw.io compatible
    XML format using the graphviz2drawio library.
    """

    def __init__(self):
        """Initialize the Draw.io Exporter."""
        super().__init__()
        self._graphviz2drawio_available = self._check_graphviz2drawio()

    def _check_graphviz2drawio(self) -> bool:
        """Check if graphviz2drawio is available.

        Returns:
            True if available, False otherwise
        """
        try:
            import graphviz2drawio

            return True
        except ImportError:
            return False

    def validate(self) -> bool:
        """Validate the exporter is properly configured.

        Returns:
            True if exporter is valid
        """
        if not self._graphviz2drawio_available:
            self.logger.warning("graphviz2drawio not installed. Install with: pip install graphviz2drawio")
            return False

        self.logger.info("DrawioExporter validated successfully")
        return True

    def export(self, graph: Digraph, output_path: str, dot_path: Optional[str] = None) -> Optional[str]:
        """Export graph to Draw.io XML format.

        Args:
            graph: Graphviz Digraph to export
            output_path: Output file path (with or without .drawio extension)
            dot_path: Optional path to save intermediate DOT file

        Returns:
            Path to generated Draw.io file if successful, None otherwise

        Example:
            >>> exporter.export(graph, "azure_resources")
            "azure_resources.drawio"
        """
        if not self._graphviz2drawio_available:
            self.logger.error("graphviz2drawio not available")
            return None

        try:
            from graphviz2drawio import graphviz2drawio

            # Ensure .drawio extension
            if not output_path.endswith(".drawio"):
                output_path = f"{output_path}.drawio"

            # Generate DOT file path if not provided
            if dot_path is None:
                base_name = output_path.replace(".drawio", "")
                dot_path = f"{base_name}.dot"

            dot_path_resolved: str = os.path.abspath(dot_path)

            # Save DOT file (graphviz2drawio needs a file path)
            with open(dot_path, "w", encoding="utf-8") as f:
                f.write(graph.source)

            self.logger.info("Converting to Draw.io XML format...")

            # Convert using graphviz2drawio
            xml = graphviz2drawio.convert(dot_path)

            # Fix hierarchy for proper nesting (if needed)
            xml = self._fix_drawio_hierarchy(graph.source, xml)

            # Save Draw.io XML
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(xml)

            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                self.logger.info(f"✓ Successfully exported Draw.io: {output_path} ({file_size:,} bytes)")
                self.logger.info("")
                self.logger.info("=" * 60)
                self.logger.info("📝 Open the .drawio file in Draw.io:")
                self.logger.info("   https://app.diagrams.net/")
                self.logger.info(f"   File → Open from → Device → Select {os.path.basename(output_path)}")
                self.logger.info("=" * 60)
                self.logger.info("")
                return output_path
            else:
                self.logger.error(f"Draw.io file not created: {output_path}")
                return None

        except ImportError:
            self.logger.error("graphviz2drawio module not installed")
            self.logger.info("Install with: pip install graphviz2drawio")
            return None
        except (IndexError, AttributeError, KeyError) as e:
            self.logger.warning(f"graphviz2drawio cannot parse this complex graph: {type(e).__name__}")
            if dot_path is not None:
                self.logger.info(f"DOT file saved at: {os.path.abspath(dot_path)}")
            self.logger.info("You can import the DOT file manually into Draw.io")
            return None
        except Exception as e:
            self.logger.error(f"Draw.io export failed: {type(e).__name__}: {e}")
            if dot_path and os.path.exists(dot_path):
                self.logger.info(f"DOT file available at: {os.path.abspath(dot_path)}")
            return None

    def _fix_drawio_hierarchy(self, dot_source: str, xml_content: str) -> str:
        """Fix Draw.io XML hierarchy for proper nested containers.

        graphviz2drawio sometimes creates flat cells instead of proper
        container groups. This method attempts to fix parent-child
        relationships.

        Args:
            dot_source: Original DOT source code
            xml_content: XML output from graphviz2drawio

        Returns:
            Fixed XML with proper nesting
        """
        # For now, return as-is. Full implementation would require
        # parsing DOT structure and updating XML parent attributes.
        # This is a placeholder for the complex hierarchy fixing logic.
        return xml_content
