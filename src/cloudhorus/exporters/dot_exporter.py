"""DOT Exporter for saving Graphviz source format."""

import os
from typing import Optional

from graphviz import Digraph

from cloudhorus.services.base import BaseService


class DOTExporter(BaseService):
    """Exporter for DOT format output.

    This exporter saves the Graphviz source code in DOT format,
    which can be edited and re-rendered later.
    """

    def __init__(self):
        """Initialize the DOT Exporter."""
        super().__init__()

    def validate(self) -> bool:
        """Validate the exporter is properly configured.

        Returns:
            True if exporter is valid
        """
        self.logger.info("DOTExporter validated successfully")
        return True

    def export(self, graph: Digraph, output_path: str) -> Optional[str]:
        """Export graph to DOT format.

        Args:
            graph: Graphviz Digraph to export
            output_path: Output file path (with or without .dot extension)

        Returns:
            Path to generated DOT file if successful, None otherwise

        Example:
            >>> exporter.export(graph, "azure_resources")
            "azure_resources.dot"
        """
        try:
            # Ensure .dot extension
            if not output_path.endswith(".dot"):
                output_path = f"{output_path}.dot"

            # Save DOT source
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(graph.source)

            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                self.logger.info(f"✓ Successfully exported DOT: {output_path} ({file_size:,} bytes)")
                return output_path
            else:
                self.logger.error(f"DOT file not created: {output_path}")
                return None

        except Exception as e:
            self.logger.error(f"Failed to export DOT: {e}")
            return None

    def get_source(self, graph: Digraph) -> str:
        """Get the DOT source code from a graph.

        Args:
            graph: Graphviz Digraph

        Returns:
            DOT source code as string
        """
        return str(graph.source)
