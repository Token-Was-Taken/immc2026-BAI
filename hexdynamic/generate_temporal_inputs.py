#!/usr/bin/env python3
"""
从 etosha8.json 模板生成支持 temporal 的四个场景 input JSON

场景定义:
- dry-day: 旱季白天 (hour=12, season=DRY)
- dry-night: 旱季夜晚 (hour=0, season=DRY)
- rainy-day: 雨季白天 (hour=12, season=RAINY)
- rainy-night: 雨季夜晚 (hour=0, season=RAINY)
"""

import json
import os


SCENARIOS = [
    {"name": "dry-day", "hour_of_day": 12, "season": "DRY"},
    {"name": "dry-night", "hour_of_day": 0, "season": "DRY"},
    {"name": "rainy-day", "hour_of_day": 12, "season": "RAINY"},
    {"name": "rainy-night", "hour_of_day": 0, "season": "RAINY"},
]

TEMPORAL_WEIGHTS = {
    "daytime_factor": 1.0,
    "nighttime_factor": 1.3,
    "dry_season_factor": 1.0,
    "rainy_season_factor": 1.2,
    "gamma": 0.3,
}


def main():
    template_path = "hexdynamic/inputs/etosha8.json"
    output_dir = "hexdynamic/inputs"
    
    with open(template_path, 'r', encoding='utf-8') as f:
        template = json.load(f)
    
    template['use_temporal_factors'] = True
    
    if 'risk_model_config' not in template:
        template['risk_model_config'] = {}
    template['risk_model_config']['temporal_weights'] = TEMPORAL_WEIGHTS
    
    for scenario in SCENARIOS:
        data = json.loads(json.dumps(template))
        data['time'] = {
            'hour_of_day': scenario['hour_of_day'],
            'season': scenario['season'],
        }
        
        output_path = os.path.join(output_dir, f"etosha8_{scenario['name']}.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"生成: {output_path}")
        print(f"  time: hour={scenario['hour_of_day']}, season={scenario['season']}")
        print(f"  use_temporal_factors: {data['use_temporal_factors']}")
        print(f"  temporal_weights: {data['risk_model_config']['temporal_weights']}")
        print()


if __name__ == '__main__':
    main()
