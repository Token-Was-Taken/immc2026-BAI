"""
marker_to_pipeline.py
从 marker 导出的 grid-coordinates.json 生成 protection_pipeline.py 的输入 JSON。

关键规则：
1. 根据 colorTag 映射地形类型
2. 犀牛(rhino)和大象(elephant)不能分布在水坑(WaterHole)和盐沼(SaltMarsh)网格
3. 鸟类(bird)集中在盐沼，其他地形密度较低

用法：
    python marker_to_pipeline.py marker/grid-coordinates.json -o marker/pipeline_input.json
"""

import argparse
import json
import math
import random
from typing import Dict, List


# colorTag 到地形类型的映射
COLOR_TAG_TO_TERRAIN = {
    1: "DenseGrass",    # 森林密集区 (绿色)
    2: "SparseGrass",   # 森林稀疏区 (红色)
    3: "WaterHole",     # 水坑 (蓝色)
    4: "SparseGrass",   # 干坑 (黄色) -> 视为稀疏草地
    5: "Road",          # 主路 (紫色)
    6: "Road",          # 小路 (橙色) -> 视为道路
    7: "SaltMarsh",     # 盐沼 (青色)
    0: "SparseGrass",   # 未知/其他 -> 默认稀疏草地
}

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

# 默认参数
DEFAULTS = {
    "total_patrol": 20,
    "total_camps": 5,
    "max_rangers_per_camp": 5,
    "total_cameras": 10,
    "total_drones": 3,
    "total_fence_length": 50,
    "patrol_radius": 5.0,
    "drone_radius": 8.0,
    "camera_radius": 3.0,
    "fence_protection": 0.5,
    "wp": 0.3,
    "wd": 0.3,
    "wc": 0.2,
    "wf": 0.2,
    "population_size": 50,
    "max_iterations": 100,
    "producer_ratio": 0.2,
    "scout_ratio": 0.2,
    "ST": 0.8,
    "R2": 0.5,
    "hour_of_day": 12,
    "season": "DRY",
    "use_temporal_factors": False,
    "human_weight": 0.4,
    "environmental_weight": 0.3,
    "density_weight": 0.3,
}


def assign_clustered_species_densities(grids_list: List[dict], grid_coords: List[dict]):
    """
    生态学驱动的物种密度分配：模拟野生动物保护区的真实分布模式。
    - 犀牛：稀疏草地，靠近水源，2-4个族群
    - 大象：稀疏草地+密林边缘，靠近水源，活动范围更大，2-3个族群
    - 鸟类：盐沼+水源附近，3-6个小群
    密度由水源距离和族群中心距离双重衰减决定。
    """
    for g in grids_list:
        g["species_densities"] = {"rhino": 0.0, "elephant": 0.0, "bird": 0.0}

    n = len(grids_list)
    if n == 0:
        return

    coord_map = {}
    for gc in grid_coords:
        coord_map[gc["gridId"]] = gc

    neighbors_map = {}
    for i, g in enumerate(grids_list):
        ogid = g.get("original_grid_id", "")
        rc = ogid.split("_") if "_" in ogid else ("0", "0")
        row, col = int(rc[0]), int(rc[1])
        neighbors_map[i] = []
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)]:
            nr, nc = row + dr, col + dc
            nid = f"{nr}_{nc}"
            for j, g2 in enumerate(grids_list):
                if g2.get("original_grid_id") == nid:
                    neighbors_map[i].append(j)
                    break

    water_indices = [i for i in range(n) if grids_list[i]["terrain_type"] == "WaterHole"]

    min_dist_to_water = {}
    for i in range(n):
        if not water_indices:
            min_dist_to_water[i] = 999
            continue
        grc = _get_rc(grids_list[i])
        min_dist_to_water[i] = min(
            ((wr := _get_rc(grids_list[w]))[0] - grc[0]) ** 2 + (wr[1] - grc[1]) ** 2
            for w in water_indices
        ) ** 0.5

    assigned = set()

    def bfs_expand(seeds, max_count, is_allowed):
        result = []
        visited = set()
        queue = [s for s in seeds if is_allowed(s)]
        for s in queue:
            visited.add(s)
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

        all_candidates = [i for i in range(n) if is_allowed(i)]
        if not all_candidates:
            continue

        scored = [(i, math.exp(-min_dist_to_water.get(i, 999) / profile["water_decay"])) for i in all_candidates]
        scored.sort(key=lambda x: x[1], reverse=True)

        num_herds = random.randint(*profile["num_herds"])
        total_max = max(1, n * profile["candidate_ratio"] // 100)
        herd_max = max(3, total_max // num_herds)

        min_seed_dist = max(5, int(math.sqrt(n) / 4))
        seed_indices = []
        for idx, _ in scored:
            if len(seed_indices) >= num_herds:
                break
            grc = _get_rc(grids_list[idx])
            too_close = any(
                ((_get_rc(grids_list[si])[0] - grc[0]) ** 2 + (_get_rc(grids_list[si])[1] - grc[1]) ** 2) ** 0.5 < min_seed_dist
                for si in seed_indices
            )
            if not too_close:
                seed_indices.append(idx)

        for seed_idx in seed_indices:
            expanded = bfs_expand([seed_idx], herd_max, is_allowed)
            src = _get_rc(grids_list[seed_idx])

            for idx in expanded:
                g = grids_list[idx]
                grc = _get_rc(g)
                d_center = ((src[0] - grc[0]) ** 2 + (src[1] - grc[1]) ** 2) ** 0.5
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

    saltmarsh_indices = [i for i in range(n) if grids_list[i]["terrain_type"] == "SaltMarsh"]
    num_bird_herds = random.randint(*bird_profile["num_herds"])
    bird_total_max = max(1, n * 5 // 100)
    bird_herd_max = max(3, bird_total_max // num_bird_herds)

    random.shuffle(saltmarsh_indices)
    bird_seeds = saltmarsh_indices[:num_bird_herds]

    for seed_idx in bird_seeds:
        expanded = bfs_expand([seed_idx], bird_herd_max, is_bird_allowed)
        src = _get_rc(grids_list[seed_idx])

        for idx in expanded:
            g = grids_list[idx]
            grc = _get_rc(g)
            d_center = ((src[0] - grc[0]) ** 2 + (src[1] - grc[1]) ** 2) ** 0.5

            herd_factor = math.exp(-d_center / bird_profile["herd_radius"])
            tt = g["terrain_type"]
            habitat_bonus = 1.0 if tt in bird_profile["habitat_terrains"] else 0.4

            val = dmin + (dmax - dmin) * herd_factor * habitat_bonus
            g["species_densities"]["bird"] = round(max(dmin, min(dmax, val)), 2)
            assigned.add(idx)


def _get_rc(grid: dict) -> tuple:
    ogid = grid.get("original_grid_id", "0_0")
    parts = ogid.split("_")
    return (int(parts[0]), int(parts[1])) if len(parts) == 2 else (0, 0)


def convert_marker_to_pipeline(grid_coords: List[dict], args) -> dict:
    """
    将 marker 导出的 grid-coordinates.json 转换为 pipeline 输入格式
    """
    random.seed(args.seed)
    
    # 解析网格ID，提取row和col的范围
    rows = set()
    cols = set()
    for grid in grid_coords:
        grid_id = grid["gridId"]
        row, col = map(int, grid_id.split("_"))
        rows.add(row)
        cols.add(col)
    
    min_row, max_row = min(rows), max(rows)
    min_col, max_col = min(cols), max(cols)
    
    # 计算地图尺寸（marker使用的坐标系）
    map_height = max_row - min_row + 1
    map_width = max_col - min_col + 1
    
    # 收集道路和水源位置
    road_locations = []
    water_locations = []
    
    # 转换网格数据
    grids = []
    grid_id_counter = 0
    
    # 创建gridId到原始数据的映射
    grid_map = {g["gridId"]: g for g in grid_coords}
    
    for grid in grid_coords:
        marker_grid_id = grid["gridId"]
        row, col = map(int, marker_grid_id.split("_"))
        
        # 获取地形类型
        color_tag = grid.get("colorTag", 0)
        terrain = COLOR_TAG_TO_TERRAIN.get(color_tag, "SparseGrass")
        
        # 坐标转换：marker的x,y已经是正确的坐标
        x = grid["x"]
        y = grid["y"]
        
        # 六边形轴坐标（从marker的row, col转换）
        # marker使用odd-r offset坐标系
        q_hex = col - (row // 2)
        r_hex = row
        
        # 生成环境风险参数
        env_fire_range, env_terrain_range = TERRAIN_ENV[terrain]
        fire_risk = round(random.uniform(*env_fire_range), 2)
        terrain_complexity = round(random.uniform(*env_terrain_range), 2)
        
        # 收集道路和水源位置
        if terrain == "Road":
            road_locations.append([x, y])
        elif terrain == "WaterHole":
            water_locations.append([x, y])
        
        grids.append({
            "grid_id": grid_id_counter,
            "original_grid_id": marker_grid_id,
            "q": q_hex,
            "r": r_hex,
            "x": x,
            "y": y,
            "hex_size": int(grid.get("hexSizeNatural", 62)),
            "terrain_type": terrain,
            "fire_risk": fire_risk,
            "terrain_complexity": terrain_complexity,
            "vegetation_type": TERRAIN_TO_VEG[terrain],
            "species_densities": {"rhino": 0.0, "elephant": 0.0, "bird": 0.0},
        })
        grid_id_counter += 1
    
    output = {
        "map_config": {
            "map_width": map_width,
            "map_height": map_height,
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
            }
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
        },
        "grids": grids,
    }
    
    return output


def parse_args():
    D = DEFAULTS
    p = argparse.ArgumentParser(
        description="从 marker 导出的 grid-coordinates.json 生成 pipeline 输入 JSON",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    
    p.add_argument("input", help="输入的 grid-coordinates.json 文件路径")
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
    
    return p.parse_args()


def main():
    args = parse_args()
    
    # 读取 marker 导出的 JSON
    with open(args.input, "r", encoding="utf-8") as f:
        grid_coords = json.load(f)
    
    if not grid_coords:
        print("错误：输入文件为空或格式不正确")
        return
    
    # 转换为 pipeline 输入格式
    output = convert_marker_to_pipeline(grid_coords, args)
    
    # 写入输出文件
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    # 统计信息
    terrain_count = {}
    rhino_grids = 0
    elephant_grids = 0
    waterhole_saltmarsh_count = 0
    
    for g in output["grids"]:
        t = g["terrain_type"]
        terrain_count[t] = terrain_count.get(t, 0) + 1
        
        if g["species_densities"]["rhino"] > 0:
            rhino_grids += 1
        if g["species_densities"]["elephant"] > 0:
            elephant_grids += 1
        if t in ["WaterHole", "SaltMarsh"]:
            waterhole_saltmarsh_count += 1
            # 验证约束
            if g["species_densities"]["rhino"] > 0 or g["species_densities"]["elephant"] > 0:
                print(f"警告：网格 {g['original_grid_id']} ({t}) 有犀牛或大象分布！")
    
    print(f"\n转换完成：{len(output['grids'])} 个网格")
    print(f"地形分布：{terrain_count}")
    print(f"道路格子：{len(output['map_config']['road_locations'])} 个")
    print(f"水源格子：{len(output['map_config']['water_locations'])} 个")
    print(f"犀牛分布网格：{rhino_grids} 个")
    print(f"大象分布网格：{elephant_grids} 个")
    print(f"水坑+盐沼网格：{waterhole_saltmarsh_count} 个（犀牛和大象密度应为0）")
    print(f"输出文件：{args.output}")


if __name__ == "__main__":
    main()
