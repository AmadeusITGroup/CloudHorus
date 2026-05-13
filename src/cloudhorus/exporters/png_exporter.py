"""PNG Exporter for rendering Graphviz graphs as PNG images."""

import os
from typing import Optional

from graphviz import Digraph

from cloudhorus.services.base import BaseService


class PNGExporter(BaseService):
    """Exporter for PNG format output.

    This exporter renders Graphviz graphs as PNG images using
    the Graphviz rendering engine.
    """

    def __init__(self):
        """Initialize the PNG Exporter."""
        super().__init__()

    def validate(self) -> bool:
        """Validate the exporter is properly configured.

        Returns:
            True if exporter is valid
        """
        try:
            # Check if Graphviz is available
            from graphviz.backend import execute

            execute.version()
            self.logger.info("PNGExporter validated successfully")
            return True
        except Exception as e:
            self.logger.error(f"PNGExporter validation failed: {e}")
            self.logger.error("Please install Graphviz: https://graphviz.org/download/")
            return False

    def export(self, graph: Digraph, output_path: str, cleanup_dot: bool = False) -> Optional[str]:
        """Export graph to PNG format.

        Args:
            graph: Graphviz Digraph to export
            output_path: Output file path (without extension)
            cleanup_dot: Whether to remove intermediate .dot file

        Returns:
            Path to generated PNG file if successful, None otherwise

        Example:
            >>> exporter.export(graph, "azure_resources_20251212_153033")
            "azure_resources_20251212_153033.png"
        """
        try:
            # Render to PNG
            graph.render(output_path, format="png", cleanup=cleanup_dot)

            png_path = f"{output_path}.png"

            if os.path.exists(png_path):
                file_size = os.path.getsize(png_path)
                self.logger.info(f"✓ Successfully exported PNG: {png_path} ({file_size:,} bytes)")
                return png_path
            else:
                self.logger.error(f"PNG file not created: {png_path}")
                return None

        except Exception as e:
            self.logger.error(f"Failed to export PNG: {e}")
            return None

    def export_with_format_options(
        self, graph: Digraph, output_path: str, dpi: int = 96, cleanup_dot: bool = False
    ) -> Optional[str]:
        """Export PNG with custom DPI settings.

        Args:
            graph: Graphviz Digraph to export
            output_path: Output file path (without extension)
            dpi: Dots per inch for output resolution
            cleanup_dot: Whether to remove intermediate .dot file

        Returns:
            Path to generated PNG file if successful, None otherwise
        """
        try:
            # Set DPI attribute
            graph.attr(dpi=str(dpi))

            # Render
            return self.export(graph, output_path, cleanup_dot)

        except Exception as e:
            self.logger.error(f"Failed to export PNG with options: {e}")
            return None
