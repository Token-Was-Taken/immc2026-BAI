import numpy as np
from typing import Dict, List
import json
import time
from data_loader import DataLoader
from grid_model import HexGridModel
from coverage_model import CoverageModel
from dssa_optimizer import DSSAOptimizer, DSSAConfig
from visualization import Visualizer


class WildlifeProtectionOptimizer:
    def __init__(self, config: Dict = None):
        self.data_loader = DataLoader()
        self.grid_model = None
        self.coverage_model = None
        self.optimizer = None
        self.visualizer = None
        self.best_solution = None
        self.best_fitness = None
        self.fitness_history = None

        if config:
            self.load_config(config)

    def load_config(self, config: Dict):
        self.data_loader.load_from_config(config)
        self._initialize_models()

    def _initialize_models(self):
        self.grid_model = HexGridModel(self.data_loader.grids)
        self.coverage_model = CoverageModel(
            self.grid_model,
            self.data_loader.coverage_params,
            self.data_loader.deployment_matrix,
            self.data_loader.visibility_params
        )
        self.visualizer = Visualizer(self.grid_model, hex_size=1.0)

    def setup_default_scenario(self, grid_width: int = 12, grid_height: int = 10):
        """设置默认场景，使用矩形六边形网格"""
        print(f"设置默认场景: 矩形网格 {grid_width} x {grid_height}")
        
        # 生成矩形六边形网格
        self.data_loader.generate_rectangular_hex_grid(width=grid_width, height=grid_height)
        
        # 生成地形和风险
        self._generate_terrain_and_risk()
        
        # 设置约束
        constraints = {
            'total_patrol': 20,
            'total_camps': 5,
            'max_rangers_per_camp': 5,
            'total_cameras': 10,
            'total_drones': 3,
            'total_fence_length': 50.0
        }
        self.data_loader.set_constraints(**constraints)
        
        # 设置覆盖参数
        coverage_params = {
            'patrol_radius': 5.0,
            'drone_radius': 8.0,
            'camera_radius': 3.0,
            'fence_protection': 0.5,
            'wp': 0.3,
            'wd': 0.3,
            'wc': 0.2,
            'wf': 0.2
        }
        self.data_loader.set_coverage_parameters(**coverage_params)
        
        # 初始化模型（需要先创建grid_model来获取边缘网格）
        temp_grid_model = HexGridModel(self.data_loader.grids)
        edge_grids = temp_grid_model.get_edge_grids()
        print(f"  边缘网格数量: {len(edge_grids)}")
        
        # 初始化矩阵（Fence只能在边缘网格部署）
        self.data_loader.initialize_deployment_matrix(edge_grids=edge_grids)
        self.data_loader.initialize_visibility_params()
        
        # 初始化模型
        self._initialize_models()

    def _generate_terrain_and_risk(self):
        import random

        terrain_types = ['SaltMarsh', 'SparseGrass', 'DenseGrass', 'WaterHole', 'Road']
        terrain_weights = [0.1, 0.4, 0.3, 0.1, 0.1]

        terrain_map = {}
        risk_map = {}

        for grid in self.data_loader.grids:
            terrain = random.choices(terrain_types, weights=terrain_weights)[0]
            terrain_map[grid.grid_id] = terrain

            base_risk = random.uniform(0.0, 0.8)

            if terrain == 'Road':
                base_risk *= 1.5
            elif terrain == 'WaterHole':
                base_risk *= 1.3
            elif terrain == 'SaltMarsh':
                base_risk *= 0.7

            risk_map[grid.grid_id] = min(1.0, base_risk)

        self.data_loader.set_terrain_types(terrain_map)
        self.data_loader.set_risk_values(risk_map)

    def run_optimization(self, dssa_config: DSSAConfig = None, verbose: bool = True):
        if not self.grid_model or not self.coverage_model:
            raise ValueError("Models not initialized. Please call setup_default_scenario() or load_config() first.")

        dssa_config = dssa_config or DSSAConfig(
            population_size=50,
            max_iterations=100,
            producer_ratio=0.2,
            scout_ratio=0.2,
            ST=0.8,
            R2=0.5
        )

        constraints = {
            'total_patrol': self.data_loader.constraints.total_patrol,
            'total_camps': self.data_loader.constraints.total_camps,
            'max_rangers_per_camp': self.data_loader.constraints.max_rangers_per_camp,
            'total_cameras': self.data_loader.constraints.total_cameras,
            'total_drones': self.data_loader.constraints.total_drones,
            'total_fence_length': self.data_loader.constraints.total_fence_length
        }

        # 将数据转换为字典格式供 DSSAOptimizer 使用
        input_grids = []
        raw_risk_map = {}
        for grid in self.data_loader.grids:
            input_grids.append({
                'grid_id': grid.grid_id,
                'q': grid.q,
                'r': grid.r,
                'x': grid.x,
                'y': grid.y,
                'terrain_type': grid.terrain_type,
                'hex_size': 1.0
            })
            raw_risk_map[grid.grid_id] = grid.risk

        self.optimizer = DSSAOptimizer(
            self.coverage_model, 
            constraints, 
            dssa_config,
            input_grids=input_grids,
            raw_risk_map=raw_risk_map
        )

        if verbose:
            print("=" * 60)
            print("Starting DSSA Optimization")
            print("=" * 60)
            print(f"Grid Size: {self.grid_model.get_grid_count()} hexagonal cells")
            print(f"Population Size: {dssa_config.population_size}")
            print(f"Max Iterations: {dssa_config.max_iterations}")
            print(f"Resources Available:")
            print(f"  - Patrol Personnel: {constraints['total_patrol']}")
            print(f"  - Patrol Camps: {constraints['total_camps']}")
            print(f"  - Cameras: {constraints['total_cameras']}")
            print(f"  - Drones: {constraints['total_drones']}")
            print(f"  - Fence Length: {constraints['total_fence_length']}")
            print("=" * 60)

        start_time = time.time()
        self.best_solution, self.best_fitness, self.fitness_history = self.optimizer.optimize()
        end_time = time.time()

        if verbose:
            print("=" * 60)
            print("Optimization Results")
            print("=" * 60)
            print(f"Best Fitness: {self.best_fitness:.4f}")
            print(f"Execution Time: {end_time - start_time:.2f} seconds")
            print("=" * 60)

        return self.best_solution, self.best_fitness, self.fitness_history

    def generate_all_visualizations(self, output_dir: str = './output'):
        import os

        if not self.best_solution:
            raise ValueError("No solution available. Please run optimization first.")

        os.makedirs(output_dir, exist_ok=True)

        print("\nGenerating visualizations...")

        self.visualizer.plot_risk_heatmap(
            save_path=f'{output_dir}/risk_heatmap.png',
            show=False
        )

        self.visualizer.plot_deployment_map(
            self.best_solution,
            save_path=f'{output_dir}/deployment_map.png',
            show=False
        )

        self.visualizer.plot_convergence_curve(
            self.fitness_history,
            save_path=f'{output_dir}/convergence_curve.png',
            show=False
        )

        self.visualizer.plot_terrain_map(
            save_path=f'{output_dir}/terrain_map.png',
            show=False
        )

        print(f"All visualizations saved to {output_dir}/")

    def print_solution_summary(self):
        if not self.best_solution:
            print("No solution available. Please run optimization first.")
            return

        stats = self.optimizer.get_solution_statistics(self.best_solution)

        print("\n" + "=" * 60)
        print("Optimal Resource Deployment Summary")
        print("=" * 60)
        print(f"Total Cameras Deployed: {stats['total_cameras']}")
        print(f"Total Drones Deployed: {stats['total_drones']}")
        print(f"Total Camps Deployed: {stats['total_camps']}")
        print(f"Total Rangers Deployed: {stats['total_rangers']}")
        print(f"Total Fence Length: {stats['total_fence_length']}")
        print(f"\nCamera Locations (Grid IDs): {stats['camera_locations']}")
        print(f"Drone Locations (Grid IDs): {stats['drone_locations']}")
        print(f"Camp Locations (Grid IDs): {stats['camp_locations']}")
        print(f"Number of Fence Segments: {len(stats['fence_edges'])}")
        print("=" * 60)

        protection_benefit = self.coverage_model.calculate_protection_benefit(self.best_solution)
        avg_benefit = np.mean(list(protection_benefit.values()))
        max_benefit = max(protection_benefit.values())
        min_benefit = min(protection_benefit.values())

        print("\nProtection Benefit Statistics:")
        print(f"Average Benefit: {avg_benefit:.4f}")
        print(f"Maximum Benefit: {max_benefit:.4f}")
        print(f"Minimum Benefit: {min_benefit:.4f}")
        print("=" * 60)

    def save_results(self, output_path: str = './output/results.json'):
        import os

        if not self.best_solution:
            raise ValueError("No solution available. Please run optimization first.")

        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)

        stats = self.optimizer.get_solution_statistics(self.best_solution)

        results = {
            'best_fitness': float(self.best_fitness),
            'fitness_history': [float(f) for f in self.fitness_history],
            'solution_stats': stats,
            'grid_count': self.grid_model.get_grid_count(),
            'terrain_distribution': self.data_loader.get_terrain_distribution()
        }

        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"Results saved to {output_path}")

    def load_results(self, input_path: str = './output/results.json'):
        with open(input_path, 'r') as f:
            results = json.load(f)

        self.best_fitness = results['best_fitness']
        self.fitness_history = results['fitness_history']

        print(f"Results loaded from {input_path}")
        print(f"Best Fitness: {self.best_fitness:.4f}")


def main():
    optimizer = WildlifeProtectionOptimizer()

    print("Setting up default scenario...")
    optimizer.setup_default_scenario()

    print("\nRunning optimization...")
    dssa_config = DSSAConfig(
        population_size=50,
        max_iterations=100,
        producer_ratio=0.2,
        scout_ratio=0.2,
        ST=0.8,
        R2=0.5
    )

    optimizer.run_optimization(dssa_config, verbose=True)

    optimizer.print_solution_summary()

    print("\nGenerating visualizations...")
    optimizer.generate_all_visualizations(output_dir='./output')

    print("\nSaving results...")
    optimizer.save_results(output_path='./output/results.json')

    print("\n" + "=" * 60)
    print("Optimization Complete!")
    print("=" * 60)
    print("\nGenerated files:")
    print("  - output/risk_heatmap.png")
    print("  - output/deployment_map.png")
    print("  - output/convergence_curve.png")
    print("  - output/terrain_map.png")
    print("  - output/results.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
