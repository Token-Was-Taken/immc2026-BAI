"""
generate_map.py
生成 m×n 规模的随机地图，直接输出 protection_pipeline.py 的输入 JSON。

地形分布规则：
  - SparseGrass / DenseGrass / WaterHole / SaltMarsh / Road 随机分配
  - 道路南北或东西贯穿地图，且不是一条直线（带随机偏移）
  - 犀牛(rhino)、大象(elephant) 只分布在 SparseGrass 网格
  - 鸟类(bird) 集中在 SaltMarsh 网格，其他地形密度极低

用法：
    python generate_map.py -m 10 -n 12 -o output.json
    python generate_map.py -m 15 -n 20 --total_patrol 30 --total_cameras 15 --season RAINY -o map.json
"""

import argparse
import json
import math
import random
import sys
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# 默认参数（与代码保持一致）
# ---------------------------------------------------------------------------
DEFAULTS = {
    # 资源约束
    "total_patrol": 20,
    "total_camps": 5,
    "max_rangers_per_camp": 5,
    "total_cameras": 10,
    "total_drones": 3,
    "total_fence_length": 50,
    # 覆盖参数
    "patrol_radius": 5.0,
    "drone_radius": 8.0,
    "camera_radius": 3.0,
    "fence_protection": 0.5,
    "wp": 0.3,
    "wd": 0.3,
    "wc": 0.2,
    "wf": 0.2,
    # DSSA
    "population_size": 50,
    "max_iterations": 1,
    "producer_ratio": 0.2,
    "scout_ratio": 0.2,
    "ST": 0.8,
    "R2": 0.5,
    # 时间
    "hour_of_day": 12,
    "season": "DRY",
    "use_temporal_factors": False,
    # 风险模型权重
    "human_weight": 0.4,
    "environmental_weight": 0.3,
    "density_weight": 0.3,
    # 人为风险权重
    "boundary_weight": 0.2,
    "road_weight": 0.3,
    "water_weight": 0.5,
    # 环境风险权重
    "fire_weight": 0.6,
    "terrain_weight": 0.4,
    # 时间因子权重
    "daytime_factor": 1.0,
    "nighttime_factor": 1.3,
    "gamma": 0.3,
    "dry_season_factor": 1.0,
    "rainy_season_factor": 1.2,
    # 物种（与 DensityRiskCalculator._get_default_species 一致）
    "hex_size": 62,
}

TERRAIN_TYPES = ["SparseGrass", "DenseGrass", "WaterHole", "SaltMarsh", "Road"]

# 地形 → riskIndex vegetation_type
TERRAIN_TO_VEG = {
    "SparseGrass": "GRASSLAND",
    "DenseGrass":  "FOREST",
    "WaterHole":   "SHRUB",
    "SaltMarsh":   "SHRUB",
    "Road":        "GRASSLAND",
}

# 地形 → 环境风险默认范围 (fire_risk_range, terrain_complexity_range)
TERRAIN_ENV = {
    "SparseGrass": ((0.2, 0.5), (0.1, 0.4)),
    "DenseGrass":  ((0.4, 0.8), (0.4, 0.7)),
    "WaterHole":   ((0.05, 0.2), (0.1, 0.3)),
    "SaltMarsh":   ((0.05, 0.2), (0.3, 0.5)),
    "Road":        ((0.1, 0.3), (0.05, 0.2)),
}


# ---------------------------------------------------------------------------
# 道路生成：南北或东西贯穿，带随机折线偏移
# ---------------------------------------------------------------------------

def generate_road_cells(m: int, n: int) -> set:
    """
    生成贯穿地图的道路格子集合。
    随机选择南北（沿行方向）或东西（沿列方向）贯穿。
    道路不是直线：每隔若干行/列随机横向偏移 ±1 格。
    m = 行数（height），n = 列数（width）
    """
    road_cells = set()
    direction = random.choice(["NS", "EW"])  # 南北 or 东西

    if direction == "NS":
        # 沿行（row）方向从上到下贯穿，列位置随机游走
        col = random.randint(1, n - 2)  # 起始列，避免边缘
        for row in range(m):
            road_cells.add((row, col))
            # 每隔 2~3 行随机偏移
            if row % random.randint(2, 3) == 0:
                shift = random.choice([-1, 0, 1])
                col = max(1, min(n - 2, col + shift))
    else:
        # 沿列（col）方向从左到右贯穿，行位置随机游走
        row = random.randint(1, m - 2)  # 起始行，避免边缘
        for col in range(n):
            road_cells.add((row, col))
            if col % random.randint(2, 3) == 0:
                shift = random.choice([-1, 0, 1])
                row = max(1, min(m - 2, row + shift))

    return road_cells


# ---------------------------------------------------------------------------
# 地形分配
# ---------------------------------------------------------------------------

def assign_terrain(m: int, n: int, road_cells: set) -> Dict[Tuple[int, int], str]:
    """
    为每个 (row, col) 分配地形类型。
    道路格子固定为 Road，其余随机分配。
    """
    # 非道路地形权重
    weights = {
        "SparseGrass": 0.40,
        "DenseGrass":  0.25,
        "WaterHole":   0.10,
        "SaltMarsh":   0.15,
        # Road 不在此分配
    }
    non_road = list(weights.keys())
    non_road_w = [weights[t] for t in non_road]

    terrain_map = {}
    for row in range(m):
        for col in range(n):
            if (row, col) in road_cells:
                terrain_map[(row, col)] = "Road"
            else:
                terrain_map[(row, col)] = random.choices(non_road, weights=non_road_w)[0]
    return terrain_map


# ---------------------------------------------------------------------------
# 物种密度生成
# ---------------------------------------------------------------------------

def generate_species_densities(terrain: str) -> Dict[str, float]:
    """
    按规则生成物种密度：
    - rhino / elephant 只在 SparseGrass 有密度，其他地形为 0
    - bird 集中在 SaltMarsh，其他地形极低
    """
    if terrain == "SparseGrass":
        return {
            "rhino":    round(random.uniform(0.4, 0.9), 2),
            "elephant": round(random.uniform(0.3, 0.8), 2),
            "bird":     round(random.uniform(0.0, 0.15), 2),
        }
    elif terrain == "SaltMarsh":
        return {
            "rhino":    0.0,
            "elephant": 0.0,
            "bird":     round(random.uniform(0.6, 1.0), 2),
        }
    elif terrain == "WaterHole":
        return {
            "rhino":    0.0,
            "elephant": 0.0,
            "bird":     round(random.uniform(0.1, 0.3), 2),
        }
    else:  # DenseGrass, Road
        return {
            "rhino":    0.0,
            "elephant": 0.0,
            "bird":     round(random.uniform(0.0, 0.1), 2),
        }


# ---------------------------------------------------------------------------
# 主生成函数
# ---------------------------------------------------------------------------

def generate(m: int, n: int, args) -> dict:
    random.seed(args.seed)

    road_cells = generate_road_cells(m, n)
    terrain_map = assign_terrain(m, n, road_cells)

    # 收集道路/水源坐标（riskIndex 用，y 轴向上）
    road_locations = []
    water_locations = []
    for row in range(m):
        for col in range(n):
            x = col
            y = m - 1 - row  # y 轴向上
            t = terrain_map[(row, col)]
            if t == "Road":
                road_locations.append([x, y])
            elif t == "WaterHole":
                water_locations.append([x, y])

    # 构建网格列表
    grids = []
    grid_id = 0
    for row in range(m):
        for col in range(n):
            terrain = terrain_map[(row, col)]
            x = col
            y = m - 1 - row

            # 六边形轴坐标（even-r offset → axial）
            # r 从下到上递增，与 marker 导出和可视化脚本一致
            r_hex = m - 1 - row
            q_hex = col - (r_hex // 2)

            env_fire_range, env_terrain_range = TERRAIN_ENV[terrain]
            fire_risk = round(random.uniform(*env_fire_range), 2)
            terrain_complexity = round(random.uniform(*env_terrain_range), 2)

            grids.append({
                "grid_id": grid_id,
                "q": q_hex,
                "r": r_hex,
                "x": x,
                "y": y,
                "hex_size": DEFAULTS["hex_size"],
                "terrain_type": terrain,
                "fire_risk": fire_risk,
                "terrain_complexity": terrain_complexity,
                "vegetation_type": TERRAIN_TO_VEG[terrain],
                "species_densities": generate_species_densities(terrain),
            })
            grid_id += 1

    output = {
        "map_config": {
            "map_width": n,
            "map_height": m,
            "boundary_type": "RECTANGLE",
            "road_locations": road_locations,
            "water_locations": water_locations,
        },
        "time": {
            "hour_of_day": args.hour_of_day,
            "season": args.season,
        },
        "use_temporal_factors": args.use_temporal_factors,
        "risk_model_config": {
            "risk_weights": {
                "human_weight": args.human_weight,
                "environmental_weight": args.environmental_weight,
                "density_weight": args.density_weight,
            },
            "human_risk_weights": {
                "boundary_weight": args.boundary_weight,
                "road_weight": args.road_weight,
                "water_weight": args.water_weight,
            },
            "environmental_risk_weights": {
                "fire_weight": args.fire_weight,
                "terrain_weight": args.terrain_weight,
            },
            "temporal_weights": {
                "daytime_factor": args.daytime_factor,
                "nighttime_factor": args.nighttime_factor,
                "gamma": args.gamma,
                "dry_season_factor": args.dry_season_factor,
                "rainy_season_factor": args.rainy_season_factor,
            },
        },
        "species_config": {
            "rhino": {
                "weight": 0.5,
                "rainy_season_multiplier": 1.2,
                "dry_season_multiplier": 1.0,
            },
            "elephant": {
                "weight": 0.3,
                "rainy_season_multiplier": 1.3,
                "dry_season_multiplier": 0.9,
            },
            "bird": {
                "weight": 0.2,
                "rainy_season_multiplier": 1.5,
                "dry_season_multiplier": 0.8,
            },
        },
        "constraints": {
            "total_patrol": args.total_patrol,
            "total_camps": args.total_camps,
            "max_rangers_per_camp": args.max_rangers_per_camp,
            "total_cameras": args.total_cameras,
            "total_drones": args.total_drones,
            "total_fence_length": args.total_fence_length,
        },
        "coverage_params": {
            "patrol_radius": args.patrol_radius,
            "drone_radius": args.drone_radius,
            "camera_radius": args.camera_radius,
            "fence_protection": args.fence_protection,
            "wp": args.wp,
            "wd": args.wd,
            "wc": args.wc,
            "wf": args.wf,
        },
        "dssa_config": {
            "population_size": args.population_size,
            "max_iterations": args.max_iterations,
            "producer_ratio": args.producer_ratio,
            "scout_ratio": args.scout_ratio,
            "ST": args.ST,
            "R2": args.R2,
            "use_marginal_contribution_repair": False,
            "skip_conflict_resolution": False,
        },
        "grids": grids,
    }

    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    D = DEFAULTS
    p = argparse.ArgumentParser(
        description="生成 m×n 随机地图，输出 protection_pipeline.py 的输入 JSON",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # 地图尺寸
    p.add_argument("-m", "--rows", type=int, default=10, metavar="M", help="地图行数")
    p.add_argument("-n", "--cols", type=int, default=12, metavar="N", help="地图列数")
    p.add_argument("-o", "--output", type=str, default="pipeline_input.json", help="输出文件路径")
    p.add_argument("--seed", type=int, default=None, help="随机种子（可复现）")

    # 时间配置
    p.add_argument("--hour_of_day", type=int, default=D["hour_of_day"], help="时间（0-23）")
    p.add_argument("--season", type=str, default=D["season"], choices=["DRY", "RAINY"], help="季节")
    p.add_argument("--use_temporal_factors", action="store_true", default=D["use_temporal_factors"],
                   help="启用昼夜/季节时间因子")

    # 资源约束
    p.add_argument("--total_patrol",        type=int,   default=D["total_patrol"])
    p.add_argument("--total_camps",         type=int,   default=D["total_camps"])
    p.add_argument("--max_rangers_per_camp",type=int,   default=D["max_rangers_per_camp"])
    p.add_argument("--total_cameras",       type=int,   default=D["total_cameras"])
    p.add_argument("--total_drones",        type=int,   default=D["total_drones"])
    p.add_argument("--total_fence_length",  type=float, default=D["total_fence_length"])

    # 覆盖参数
    p.add_argument("--patrol_radius",   type=float, default=D["patrol_radius"])
    p.add_argument("--drone_radius",    type=float, default=D["drone_radius"])
    p.add_argument("--camera_radius",   type=float, default=D["camera_radius"])
    p.add_argument("--fence_protection",type=float, default=D["fence_protection"])
    p.add_argument("--wp", type=float, default=D["wp"], help="巡逻权重")
    p.add_argument("--wd", type=float, default=D["wd"], help="无人机权重")
    p.add_argument("--wc", type=float, default=D["wc"], help="摄像头权重")
    p.add_argument("--wf", type=float, default=D["wf"], help="围栏权重")

    # DSSA
    p.add_argument("--population_size", type=int,   default=D["population_size"])
    p.add_argument("--max_iterations",  type=int,   default=D["max_iterations"])
    p.add_argument("--producer_ratio",  type=float, default=D["producer_ratio"])
    p.add_argument("--scout_ratio",     type=float, default=D["scout_ratio"])
    p.add_argument("--ST",              type=float, default=D["ST"])
    p.add_argument("--R2",              type=float, default=D["R2"])

    # 风险模型权重
    p.add_argument("--human_weight",        type=float, default=D["human_weight"])
    p.add_argument("--environmental_weight",type=float, default=D["environmental_weight"])
    p.add_argument("--density_weight",      type=float, default=D["density_weight"])

    # 人为风险权重
    p.add_argument("--boundary_weight", type=float, default=D["boundary_weight"], help="边界邻近度权重")
    p.add_argument("--road_weight",     type=float, default=D["road_weight"], help="道路邻近度权重")
    p.add_argument("--water_weight",    type=float, default=D["water_weight"], help="水源邻近度权重")

    # 环境风险权重
    p.add_argument("--fire_weight",    type=float, default=D["fire_weight"], help="火灾风险权重")
    p.add_argument("--terrain_weight", type=float, default=D["terrain_weight"], help="地形复杂度权重")

    # 时间因子权重
    p.add_argument("--daytime_factor",      type=float, default=D["daytime_factor"], help="白天风险因子")
    p.add_argument("--nighttime_factor",    type=float, default=D["nighttime_factor"], help="夜间风险因子")
    p.add_argument("--gamma",               type=float, default=D["gamma"], help="昼夜正弦波振幅")
    p.add_argument("--dry_season_factor",   type=float, default=D["dry_season_factor"], help="旱季风险因子")
    p.add_argument("--rainy_season_factor", type=float, default=D["rainy_season_factor"], help="雨季风险因子")

    return p.parse_args()


def main():
    args = parse_args()
    m, n = args.rows, args.cols

    if m < 3 or n < 3:
        print("错误：地图尺寸至少为 3×3", file=sys.stderr)
        sys.exit(1)

    data = generate(m, n, args)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # 统计地形分布
    terrain_count: Dict[str, int] = {}
    for g in data["grids"]:
        t = g["terrain_type"]
        terrain_count[t] = terrain_count.get(t, 0) + 1

    print(f"地图生成完成：{m} 行 × {n} 列 = {m*n} 个网格")
    print(f"地形分布：{terrain_count}")
    print(f"道路格子：{len(data['map_config']['road_locations'])} 个")
    print(f"水源格子：{len(data['map_config']['water_locations'])} 个")
    print(f"输出文件：{args.output}")


if __name__ == "__main__":
    main()
