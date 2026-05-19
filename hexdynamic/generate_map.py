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
    "max_iterations": 200,
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
    # DSSA 高级配置
    "save_iteration_visualization": False,
    "use_risk_priority": True,
    "high_risk_percentage": 0.1,
    "force_full_deployment": True,
    "high_risk_perturbation_priority": 0.7,
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

def assign_clustered_species_densities(grids_list: List[dict], m: int, n: int):
    """
    生态学驱动的物种密度分配：模拟野生动物保护区的真实分布模式。
    - 犀牛：稀疏草地，靠近水源，2-4个族群
    - 大象：稀疏草地+密林边缘，靠近水源，活动范围更大，2-3个族群
    - 鸟类：盐沼+水源附近，3-6个小群
    密度由水源距离和族群中心距离双重衰减决定。
    """
    for g in grids_list:
        g["species_densities"] = {"rhino": 0.0, "elephant": 0.0, "bird": 0.0}

    total = len(grids_list)
    if total == 0:
        return

    idx_map = {}
    for i, g in enumerate(grids_list):
        key = (g["x"], g["y"])
        idx_map[key] = i

    neighbors_map = {}
    for i, g in enumerate(grids_list):
        x, y = g["x"], g["y"]
        neighbors_map[i] = []
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx_key = (x + dx, y + dy)
            if nx_key in idx_map:
                neighbors_map[i].append(idx_map[nx_key])

    water_indices = [i for i in range(total) if grids_list[i]["terrain_type"] == "WaterHole"]

    min_dist_to_water = {}
    for i in range(total):
        if not water_indices:
            min_dist_to_water[i] = 999
            continue
        gx, gy = grids_list[i]["x"], grids_list[i]["y"]
        min_dist_to_water[i] = min(
            ((grids_list[w]["x"] - gx) ** 2 + (grids_list[w]["y"] - gy) ** 2) ** 0.5
            for w in water_indices
        )

    assigned = set()

    def bfs_expand(seeds, max_count, is_allowed):
        result = []
        visited = set()
        queue = list(seeds)
        for s in seeds:
            if is_allowed(s):
                visited.add(s)
        queue = [s for s in seeds if is_allowed(s)]
        while queue and len(result) < max_count:
            idx = queue.pop(0)
            if idx in assigned:
                continue
            result.append(idx)
            for nb in neighbors_map.get(idx, []):
                if nb not in visited and nb not in assigned and is_allowed(nb):
                    visited.add(nb)
                    queue.append(nb)
        return result

    species_profiles = {
        "rhino": {
            "habitat_terrains": {"SparseGrass"},
            "water_decay": 8,
            "herd_radius": 6,
            "num_herds": (2, 4),
            "density_range": (0.4, 1.0),
            "candidate_ratio": 5,
        },
        "elephant": {
            "habitat_terrains": {"SparseGrass", "DenseGrass"},
            "water_decay": 12,
            "herd_radius": 8,
            "num_herds": (2, 3),
            "density_range": (0.3, 0.9),
            "candidate_ratio": 5,
        },
    }

    for species, profile in species_profiles.items():
        dmin, dmax = profile["density_range"]
        is_allowed = lambda idx, ht=profile["habitat_terrains"]: (
            grids_list[idx]["terrain_type"] in ht and grids_list[idx]["terrain_type"] != "Road"
        )

        all_candidates = [i for i in range(total) if is_allowed(i)]
        if not all_candidates:
            continue

        scored = [(i, math.exp(-min_dist_to_water.get(i, 999) / profile["water_decay"])) for i in all_candidates]
        scored.sort(key=lambda x: x[1], reverse=True)

        num_herds = random.randint(*profile["num_herds"])
        total_max = max(1, total * profile["candidate_ratio"] // 100)
        herd_max = max(3, total_max // num_herds)

        min_seed_dist = max(5, int(math.sqrt(total) / 4))
        seed_indices = []
        for idx, _ in scored:
            if len(seed_indices) >= num_herds:
                break
            gx, gy = grids_list[idx]["x"], grids_list[idx]["y"]
            too_close = any(
                ((grids_list[si]["x"] - gx) ** 2 + (grids_list[si]["y"] - gy) ** 2) ** 0.5 < min_seed_dist
                for si in seed_indices
            )
            if not too_close:
                seed_indices.append(idx)

        for seed_idx in seed_indices:
            expanded = bfs_expand([seed_idx], herd_max, is_allowed)
            sx, sy = grids_list[seed_idx]["x"], grids_list[seed_idx]["y"]

            for idx in expanded:
                g = grids_list[idx]
                d_center = ((g["x"] - sx) ** 2 + (g["y"] - sy) ** 2) ** 0.5
                dw = min_dist_to_water.get(idx, 999)

                herd_factor = math.exp(-d_center / profile["herd_radius"])
                water_factor = math.exp(-dw / profile["water_decay"])
                combined = herd_factor * (0.4 + 0.6 * water_factor)

                val = dmin + (dmax - dmin) * combined
                g["species_densities"][species] = round(max(dmin, min(dmax, val)), 2)
                assigned.add(idx)

    bird_profile = {
        "habitat_terrains": {"SaltMarsh", "WaterHole"},
        "herd_radius": 5,
        "num_herds": (3, 6),
        "density_range": (0.5, 1.0),
    }
    dmin, dmax = bird_profile["density_range"]
    is_bird_allowed = lambda idx: grids_list[idx]["terrain_type"] != "Road"

    saltmarsh_indices = [i for i in range(total) if grids_list[i]["terrain_type"] == "SaltMarsh"]
    num_bird_herds = random.randint(*bird_profile["num_herds"])
    bird_total_max = max(1, total * 5 // 100)
    bird_herd_max = max(3, bird_total_max // num_bird_herds)

    random.shuffle(saltmarsh_indices)
    bird_seeds = saltmarsh_indices[:num_bird_herds]

    for seed_idx in bird_seeds:
        expanded = bfs_expand([seed_idx], bird_herd_max, is_bird_allowed)
        sx, sy = grids_list[seed_idx]["x"], grids_list[seed_idx]["y"]

        for idx in expanded:
            g = grids_list[idx]
            d_center = ((g["x"] - sx) ** 2 + (g["y"] - sy) ** 2) ** 0.5

            herd_factor = math.exp(-d_center / bird_profile["herd_radius"])
            tt = g["terrain_type"]
            habitat_bonus = 1.0 if tt in bird_profile["habitat_terrains"] else 0.4

            val = dmin + (dmax - dmin) * herd_factor * habitat_bonus
            g["species_densities"]["bird"] = round(max(dmin, min(dmax, val)), 2)
            assigned.add(idx)


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
                "species_densities": {"rhino": 0.0, "elephant": 0.0, "bird": 0.0},
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
            "save_iteration_visualization": args.save_iteration_visualization,
            "use_risk_priority": args.use_risk_priority,
            "high_risk_percentage": args.high_risk_percentage,
            "force_full_deployment": args.force_full_deployment,
            "high_risk_perturbation_priority": args.high_risk_perturbation_priority,
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

    # DSSA 高级配置
    p.add_argument("--save_iteration_visualization", action="store_true", default=D["save_iteration_visualization"],
                   help="保存迭代可视化")
    p.add_argument("--use_risk_priority", action="store_true", default=D["use_risk_priority"],
                   help="启用风险优先部署")
    p.add_argument("--high_risk_percentage", type=float, default=D["high_risk_percentage"],
                   help="高风险网格占比（0-1）")
    p.add_argument("--force_full_deployment", action="store_true", default=D["force_full_deployment"],
                   help="强制部署模式")
    p.add_argument("--high_risk_perturbation_priority", type=float, default=D["high_risk_perturbation_priority"],
                   help="高风险扰动优先级（0-1）")

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
