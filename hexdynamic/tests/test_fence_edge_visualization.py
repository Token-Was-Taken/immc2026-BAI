"""
Unit tests for fence edge visualization.

Tests that fence edges are drawn with correct line width and color.

Validates: Requirements 3.1, 3.2, 3.3
"""

import pytest
import json
import os
import tempfile
import math
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import visualization module
import visualize_output as viz


class TestFenceEdgeVisualization:
    """Tests for fence edge visualization functions."""
    
    def test_fence_edge_linewidth_constant(self):
        """Test that fence edge line width is 2.5x regular edge width."""
        regular_edge_width = 0.4
        expected_linewidth = regular_edge_width * 2.5
        
        assert viz.FENCE_EDGE_LINEWIDTH == expected_linewidth, \
            f"Fence edge line width should be {expected_linewidth} (2.5x regular)"
    
    def test_fence_edge_color_is_distinct(self):
        """Test that fence edge color is distinct from other map elements."""
        # Fence color should be different from terrain colors
        fence_color = viz.FENCE_COLOR
        
        # Check it's different from all terrain colors
        for terrain_name, terrain_color in viz.TERRAIN_COLORS.items():
            assert fence_color != terrain_color, \
                f"Fence color {fence_color} should differ from {terrain_name} color {terrain_color}"
        
        # Check it's a valid hex color
        assert fence_color.startswith("#"), "Fence color should be a hex color"
        assert len(fence_color) == 7, "Fence color should be 7 characters (#RRGGBB)"
    
    def test_draw_deployed_fence_edges_empty_input(self):
        """Test that draw_deployed_fence_edges handles empty fence_edges."""
        # Create mock axes
        mock_ax = Mock()
        
        # Create test data with no fence edges
        grids = [{"grid_id": 0, "q": 0, "r": 0}]
        out = {"fence_edges": []}
        
        # Should not raise any errors
        viz.draw_deployed_fence_edges(mock_ax, grids, out, hex_size=1.0)
        
        # Should not have drawn anything
        mock_ax.plot.assert_not_called()
    
    def test_draw_deployed_fence_edges_internal_edge(self):
        """Test that draw_deployed_fence_edges draws internal fence edges."""
        # Create mock axes
        mock_ax = Mock()
        
        # Create test data with two adjacent grids and a fence between them
        grids = [
            {"grid_id": 0, "q": 0, "r": 0},
            {"grid_id": 1, "q": 1, "r": 0}  # East neighbor
        ]
        out = {
            "fence_edges": [
                {"grid_id_1": 0, "grid_id_2": 1}
            ]
        }
        
        # Call the function
        viz.draw_deployed_fence_edges(mock_ax, grids, out, hex_size=1.0)
        
        # Should have drawn the fence edge
        assert mock_ax.plot.called, "Should have drawn fence edge"
        
        # Check the call arguments
        call_args = mock_ax.plot.call_args
        assert call_args is not None
        
        # Check color is fence color
        kwargs = call_args[1]
        assert kwargs.get('color') == viz.FENCE_COLOR, \
            f"Fence edge should use fence color {viz.FENCE_COLOR}"
        
        # Check line width
        assert kwargs.get('lw') == viz.FENCE_EDGE_LINEWIDTH, \
            f"Fence edge should have line width {viz.FENCE_EDGE_LINEWIDTH}"
    
    def test_draw_deployed_fence_edges_boundary_edge(self):
        """Test that draw_deployed_fence_edges draws boundary fence edges."""
        # Create mock axes
        mock_ax = Mock()
        
        # Create test data with a single grid and a boundary fence
        grids = [
            {"grid_id": 0, "q": 0, "r": 0}
        ]
        out = {
            "fence_edges": [
                {"grid_id_1": 0, "grid_id_2": None, "direction": 0}  # East boundary
            ]
        }
        
        # Call the function
        viz.draw_deployed_fence_edges(mock_ax, grids, out, hex_size=1.0)
        
        # Should have drawn the fence edge
        assert mock_ax.plot.called, "Should have drawn boundary fence edge"
        
        # Check the call arguments
        call_args = mock_ax.plot.call_args
        kwargs = call_args[1]
        
        # Check color is fence color
        assert kwargs.get('color') == viz.FENCE_COLOR, \
            f"Boundary fence edge should use fence color {viz.FENCE_COLOR}"
        
        # Check line width
        assert kwargs.get('lw') == viz.FENCE_EDGE_LINEWIDTH, \
            f"Boundary fence edge should have line width {viz.FENCE_EDGE_LINEWIDTH}"
    
    def test_draw_deployed_fence_edges_uses_correct_zorder(self):
        """Test that fence edges are drawn with correct zorder (above other elements)."""
        mock_ax = Mock()
        
        grids = [
            {"grid_id": 0, "q": 0, "r": 0},
            {"grid_id": 1, "q": 1, "r": 0}
        ]
        out = {
            "fence_edges": [
                {"grid_id_1": 0, "grid_id_2": 1}
            ]
        }
        
        viz.draw_deployed_fence_edges(mock_ax, grids, out, hex_size=1.0)
        
        call_args = mock_ax.plot.call_args
        kwargs = call_args[1]
        
        # zorder should be higher than regular elements (typically 1-5)
        assert kwargs.get('zorder', 0) >= 7, \
            "Fence edges should have zorder >= 7 to appear above other elements"
    
    def test_draw_deployed_fence_edges_multiple_edges(self):
        """Test that multiple fence edges are all drawn."""
        mock_ax = Mock()
        
        # Create a small grid with multiple fence edges
        grids = [
            {"grid_id": 0, "q": 0, "r": 0},
            {"grid_id": 1, "q": 1, "r": 0},
            {"grid_id": 2, "q": 0, "r": 1}
        ]
        out = {
            "fence_edges": [
                {"grid_id_1": 0, "grid_id_2": 1},
                {"grid_id_1": 0, "grid_id_2": 2}
            ]
        }
        
        viz.draw_deployed_fence_edges(mock_ax, grids, out, hex_size=1.0)
        
        # Should have drawn both fence edges
        assert mock_ax.plot.call_count == 2, \
            "Should have drawn 2 fence edges"


class TestFenceEdgeVisualizationIntegration:
    """Integration tests for fence edge visualization."""
    
    def test_plot_terrain_deployment_map_calls_draw_fence_edges(self):
        """Test that plot_terrain_deployment_map calls draw_deployed_fence_edges."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test output data
            out = {
                "grids": [
                    {
                        "grid_id": 0, "q": 0, "r": 0, "x": 0.0, "y": 0.0,
                        "terrain_type": "SparseGrass",
                        "risk_normalized": 0.5,
                        "deployment": {"camera": 0, "drone": 0, "patrol_rangers": 0}
                    },
                    {
                        "grid_id": 1, "q": 1, "r": 0, "x": 1.732, "y": 0.0,
                        "terrain_type": "DenseGrass",
                        "risk_normalized": 0.3,
                        "deployment": {"camera": 1, "drone": 0, "patrol_rangers": 0}
                    }
                ],
                "summary": {
                    "total_grids": 2,
                    "best_fitness": 0.5,
                    "total_protection_benefit": 0.5,
                    "average_protection_benefit": 0.25
                },
                "fence_edges": [
                    {"grid_id_1": 0, "grid_id_2": 1}
                ]
            }
            
            # Save to temp file
            output_path = os.path.join(tmpdir, "test_output.json")
            with open(output_path, "w") as f:
                json.dump(out, f)
            
            save_path = os.path.join(tmpdir, "test_map.png")
            
            # Patch draw_deployed_fence_edges to verify it's called
            with patch.object(viz, 'draw_deployed_fence_edges') as mock_draw:
                viz.plot_terrain_deployment_map(out, hex_size=1.0, boundary_xy=None, save_path=save_path)
                
                # Verify draw_deployed_fence_edges was called
                mock_draw.assert_called_once()
                
                # Verify it was called with correct arguments
                call_args = mock_draw.call_args
                assert call_args[0][1] == out["grids"], "Should pass grids"
                assert call_args[0][2] == out, "Should pass output data"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
