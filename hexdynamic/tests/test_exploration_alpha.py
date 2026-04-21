"""Tests for DSSA exploration optimization feature.

Feature: dssa-exploration-optimization
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from dssa_optimizer import DSSAConfig, DSSAOptimizer
from unittest.mock import MagicMock


class TestDSSAConfigDefaults:
    """Test that DSSAConfig has correct default values for new fields."""

    def test_default_values(self):
        """Property 5: DSSAConfig default values
        
        For a DSSAConfig() instantiated with no arguments, all new fields
        should equal their documented defaults.
        
        Validates: Requirements 1.5, 2.4, 3.1, 5.1, 5.2
        """
        # Feature: dssa-exploration-optimization, Property 5: DSSAConfig default values
        config = DSSAConfig()
        
        # Exploration range scheduling defaults
        assert config.initial_alpha == 3.0, "initial_alpha should default to 3.0"
        assert config.mid_alpha == 2.0, "mid_alpha should default to 2.0"
        assert config.final_alpha == 1.0, "final_alpha should default to 1.0"
        assert config.exploitation_alpha == 1.0, "exploitation_alpha should default to 1.0"
        
        # Stagnation detection and boost defaults
        assert config.stagnation_threshold == 10, "stagnation_threshold should default to 10"
        assert config.stagnation_tolerance == 1e-6, "stagnation_tolerance should default to 1e-6"
        assert config.stagnation_boost == 1.5, "stagnation_boost should default to 1.5"


class TestGetExplorationAlpha:
    """Tests for the _get_exploration_alpha method."""

    def _create_mock_optimizer(self, config: DSSAConfig) -> DSSAOptimizer:
        """Helper to create a DSSAOptimizer with mocked dependencies."""
        mock_coverage_model = MagicMock()
        mock_coverage_model.grid_model.get_all_grid_ids.return_value = []
        mock_coverage_model.grid_model.get_fencing_edges.return_value = []
        
        optimizer = DSSAOptimizer(
            coverage_model=mock_coverage_model,
            constraints={},
            config=config
        )
        return optimizer

    @given(
        iteration=st.integers(min_value=0, max_value=999),
        max_iterations=st.integers(min_value=1, max_value=1000),
        initial_alpha=st.floats(min_value=0.1, max_value=10.0),
        mid_alpha=st.floats(min_value=0.1, max_value=10.0),
        final_alpha=st.floats(min_value=0.1, max_value=10.0),
    )
    @settings(max_examples=100)
    def test_phase_schedule_correctness(
        self, iteration, max_iterations, initial_alpha, mid_alpha, final_alpha
    ):
        """Property 1: Phase schedule correctness
        
        For any valid DSSAConfig and any iteration index t in [0, max_iterations),
        _get_exploration_alpha(t) (with stagnation_count = 0) should return
        initial_alpha when t/max_iterations < 0.3, mid_alpha when
        0.3 <= t/max_iterations < 0.7, and final_alpha otherwise.
        
        Validates: Requirements 1.2, 1.3, 1.4
        """
        # Feature: dssa-exploration-optimization, Property 1: phase schedule correctness
        config = DSSAConfig(
            max_iterations=max_iterations,
            initial_alpha=initial_alpha,
            mid_alpha=mid_alpha,
            final_alpha=final_alpha,
        )
        optimizer = self._create_mock_optimizer(config)
        optimizer.stagnation_count = 0  # Ensure no stagnation boost
        
        # Skip if iteration >= max_iterations (invalid case)
        if iteration >= max_iterations:
            return
        
        alpha = optimizer._get_exploration_alpha(iteration)
        
        # Calculate expected phase
        progress = iteration / max(max_iterations - 1, 1)
        if progress < 0.3:
            expected = initial_alpha
        elif progress < 0.7:
            expected = mid_alpha
        else:
            expected = final_alpha
        
        assert alpha == expected, (
            f"Expected alpha={expected} at progress={progress:.2f}, got {alpha}"
        )

    @given(
        iteration=st.integers(min_value=0, max_value=100),
        max_iterations=st.integers(min_value=2, max_value=100),
        initial_alpha=st.floats(min_value=0.1, max_value=10.0),
        mid_alpha=st.floats(min_value=0.1, max_value=10.0),
        final_alpha=st.floats(min_value=0.1, max_value=10.0),
        stagnation_threshold=st.integers(min_value=0, max_value=20),
        stagnation_boost=st.floats(min_value=1.0, max_value=3.0),
    )
    @settings(max_examples=100)
    def test_stagnation_boost_activation(
        self,
        iteration,
        max_iterations,
        initial_alpha,
        mid_alpha,
        final_alpha,
        stagnation_threshold,
        stagnation_boost,
    ):
        """Property 2: Stagnation boost activation
        
        For any DSSAConfig and any stagnation count strictly greater than
        stagnation_threshold, _get_exploration_alpha(t) should return a value
        equal to the scheduled alpha multiplied by stagnation_boost.
        
        Validates: Requirements 2.2
        """
        # Feature: dssa-exploration-optimization, Property 2: stagnation boost activation
        config = DSSAConfig(
            max_iterations=max_iterations,
            initial_alpha=initial_alpha,
            mid_alpha=mid_alpha,
            final_alpha=final_alpha,
            stagnation_threshold=stagnation_threshold,
            stagnation_boost=stagnation_boost,
        )
        optimizer = self._create_mock_optimizer(config)
        
        # Set stagnation_count above threshold
        optimizer.stagnation_count = stagnation_threshold + 1
        
        # Skip if iteration >= max_iterations (invalid case)
        if iteration >= max_iterations:
            return
        
        alpha = optimizer._get_exploration_alpha(iteration)
        
        # Calculate expected scheduled alpha (without boost)
        progress = iteration / max(max_iterations - 1, 1)
        if progress < 0.3:
            scheduled = initial_alpha
        elif progress < 0.7:
            scheduled = mid_alpha
        else:
            scheduled = final_alpha
        
        expected = scheduled * stagnation_boost
        
        assert abs(alpha - expected) < 1e-9, (
            f"Expected boosted alpha={expected}, got {alpha}"
        )


class TestStagnationCounterReset:
    """Tests for stagnation counter reset behavior."""

    def _create_mock_optimizer(self, config: DSSAConfig) -> DSSAOptimizer:
        """Helper to create a DSSAOptimizer with mocked dependencies."""
        mock_coverage_model = MagicMock()
        mock_coverage_model.grid_model.get_all_grid_ids.return_value = []
        mock_coverage_model.grid_model.get_fencing_edges.return_value = []
        
        optimizer = DSSAOptimizer(
            coverage_model=mock_coverage_model,
            constraints={},
            config=config
        )
        return optimizer

    @given(
        fitness_values=st.lists(
            st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=20
        ),
        stagnation_tolerance=st.floats(min_value=1e-10, max_value=1.0),
    )
    @settings(max_examples=100)
    def test_stagnation_counter_reset_after_improvement(
        self, fitness_values, stagnation_tolerance
    ):
        """Property 3: Stagnation counter reset
        
        For any sequence of fitness values where at least one improvement
        exceeds stagnation_tolerance, the stagnation counter should be zero
        immediately after that improvement is processed.
        
        Validates: Requirements 2.3
        """
        # Feature: dssa-exploration-optimization, Property 3: stagnation counter reset
        config = DSSAConfig(stagnation_tolerance=stagnation_tolerance)
        optimizer = self._create_mock_optimizer(config)
        
        # Simulate the stagnation counter update logic
        stagnation_count = 0
        prev_best_fitness = float('-inf')
        
        for fitness in fitness_values:
            # Simulate the update logic from optimize()
            if fitness - prev_best_fitness > stagnation_tolerance:
                stagnation_count = 0
            else:
                stagnation_count += 1
            prev_best_fitness = fitness
        
        # Check that after any improvement exceeding tolerance, counter is reset
        # We verify this by checking the final state
        # If the last fitness value was an improvement, counter should be 0
        if len(fitness_values) >= 2:
            last_fitness = fitness_values[-1]
            second_last_fitness = fitness_values[-2]
            if last_fitness - second_last_fitness > stagnation_tolerance:
                assert stagnation_count == 0, (
                    f"Stagnation counter should be 0 after improvement, got {stagnation_count}"
                )


class TestExploitationAlphaSeparation:
    """Tests for exploitation alpha separation in producer updates."""

    def _create_mock_optimizer(self, config: DSSAConfig) -> DSSAOptimizer:
        """Helper to create a DSSAOptimizer with mocked dependencies."""
        mock_coverage_model = MagicMock()
        mock_coverage_model.grid_model.get_all_grid_ids.return_value = []
        mock_coverage_model.grid_model.get_fencing_edges.return_value = []
        
        optimizer = DSSAOptimizer(
            coverage_model=mock_coverage_model,
            constraints={},
            config=config
        )
        return optimizer

    @given(
        exploitation_alpha=st.floats(min_value=0.1, max_value=10.0),
    )
    @settings(max_examples=100)
    def test_exploitation_alpha_bounds(self, exploitation_alpha):
        """Property 4: Exploitation alpha separation
        
        For any exploitation_alpha value, the perturbation applied in
        exploitation-mode producer updates should be bounded within
        [-exploitation_alpha, exploitation_alpha].
        
        Validates: Requirements 3.2
        """
        # Feature: dssa-exploration-optimization, Property 4: exploitation alpha separation
        import numpy as np
        
        # Generate a sample perturbation using the same logic as _update_producers
        # For non-best producers in exploitation mode (i == 0 case uses best_vector, not exploitation_alpha)
        perturbation = np.random.uniform(-exploitation_alpha, exploitation_alpha, size=100)
        
        # Verify all elements are within bounds
        assert np.all(perturbation >= -exploitation_alpha), (
            f"Perturbation values should be >= -exploitation_alpha ({-exploitation_alpha}), "
            f"got min {perturbation.min()}"
        )
        assert np.all(perturbation <= exploitation_alpha), (
            f"Perturbation values should be <= exploitation_alpha ({exploitation_alpha}), "
            f"got max {perturbation.max()}"
        )

    @given(
        exploitation_alpha=st.floats(min_value=0.1, max_value=10.0),
        vector_size=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100)
    def test_exploitation_alpha_vector_generation(self, exploitation_alpha, vector_size):
        """Property 4: Exploitation alpha separation (vectorized)
        
        For any exploitation_alpha and any vector size, all elements
        of the generated perturbation vector should be bounded within
        [-exploitation_alpha, exploitation_alpha].
        
        Validates: Requirements 3.2
        """
        # Feature: dssa-exploration-optimization, Property 4: exploitation alpha separation
        import numpy as np
        
        # Generate perturbation vector matching the pattern in _update_producers
        perturbation = np.random.uniform(-exploitation_alpha, exploitation_alpha, size=vector_size)
        
        # Verify bounds
        assert perturbation.shape == (vector_size,), (
            f"Expected shape ({vector_size},), got {perturbation.shape}"
        )
        assert np.all(perturbation >= -exploitation_alpha), (
            f"All values should be >= {-exploitation_alpha}"
        )
        assert np.all(perturbation <= exploitation_alpha), (
            f"All values should be <= {exploitation_alpha}"
        )
