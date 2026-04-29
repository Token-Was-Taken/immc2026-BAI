# IMM C 2026 - Wildlife Reserve Resource Optimization System

## Directory Structure

```
immc2026/
├── hexdynamic/      # Hexagonal Grid Dynamic Resource Optimization System
├── marker/          # Image Viewer and Grid Marking Tool
└── riskIndex/       # Protected Area Grid Risk Index Model
```

---

## hexdynamic/ - Hexagonal Grid Dynamic Resource Optimization System

### Overview

A wildlife reserve resource deployment optimization system based on hexagonal honeycomb grids, using DSSA (Dynamic Sparrow Search Algorithm) to optimize the deployment of patrol personnel, UAVs, surveillance cameras, base camps, and fences.

### Core Modules

| File | Function |
|------|----------|
| `main.py` | Main program entry point, complete workflow control |
| `demo.py` | Demo program driven by JSON configuration |
| `batch_run.py` | Batch run script for testing multiple resource configurations |
| `data_loader.py` | Data loading, grid generation, constraint management |
| `grid_model.py` | Hexagonal grid model, distance calculation, adjacency relationships |
| `coverage_model.py` | Protection coverage calculation, benefit evaluation |
| `dssa_optimizer.py` | DSSA optimization algorithm implementation |
| `dynamic_coverage_model.py` | Time-dynamic protection analysis |
| `visualization.py` | Visualization and plotting |

### Key Models & Formulas

#### 1. Hexagonal Grid Distance Calculation
```
Hexagonal distance = max(|q1-q2|, |r1-r2|, |s1-s2|)
where s = -q - r
```

#### 2. Patrol Coverage Model (Exponential Decay)
```
Patrol intensity = Σ [rangers × exp(-distance / patrol_radius)]
Patrol coverage = 1 - exp(-patrol intensity)
```

#### 3. Comprehensive Protection Benefit (with Synergy)

```
Base model:
  E_i = wp × patrol_cov + wd × drone_cov + wc × camera_cov + wf × fence_prot

Collaborative enhancement (Patrol + Drone, Patrol + Camera):
  E_i = Base + α_pd × (P×D)/(1+P+D) + α_pc × (P×C)/(1+P+C)

Where:
  P = patrol_coverage, D = drone_coverage, C = camera_coverage
  α_pd ∈ [0.3, 0.5] (default 0.4) — Patrol/Drone synergy coefficient
  α_pc ∈ [0.1, 0.2] (default 0.15) — Patrol/Camera synergy coefficient

Normalized synergy form prevents explosive growth while preserving collaborative benefits.

Protection benefit B_i = Risk value R_i × (1 - exp(-E_i))
Total protection benefit = ΣB_i / ΣR_i (normalized)
```

### Key Parameters (Default Values)

#### Coverage Parameters (`CoverageParameters`)
| Parameter | Default | Description |
|-----------|---------|-------------|
| `patrol_radius` | 5.0 | Patrol personnel effective radius |
| `drone_radius` | 8.0 | UAV effective radius |
| `camera_radius` | 3.0 | Camera effective radius |
| `fence_protection` | 0.5 | Fence protection coefficient |
| `wp` | 0.3 | Patrol weight |
| `wd` | 0.3 | UAV weight |
| `wc` | 0.2 | Camera weight |
| `wf` | 0.2 | Fence weight |
| `alpha_pd` | 0.4 | **Patrol+Drone synergy coefficient** (range: 0.3–0.5) |
| `alpha_pc` | 0.15 | **Patrol+Camera synergy coefficient** (range: 0.1–0.2) |

#### DSSA Algorithm Parameters (`DSSAConfig`)
| Parameter | Default | Description |
|-----------|---------|-------------|
| `population_size` | 50 | Population size |
| `max_iterations` | 100 | Maximum iterations |
| `producer_ratio` | 0.2 | Producer ratio |
| `scout_ratio` | 0.2 | Scout ratio |
| `ST` | 0.8 | Stability threshold |
| `R2` | 0.5 | Exploration parameter |

#### Resource Constraints
| Parameter | Default | Description |
|-----------|---------|-------------|
| `total_patrol` | 20 | Total patrol personnel |
| `total_camps` | 5 | Total base camps |
| `max_rangers_per_camp` | 5 | Max rangers per camp |
| `total_cameras` | 10 | Total cameras |
| `total_drones` | 3 | Total UAVs |
| `total_fence_length` | 50.0 | Total fence length |

### Input & Output

#### Input
- `demo_config.json` - Configuration file containing grid size, risk configuration, resource inventory, coverage parameters, etc.

#### Output (demo.py)
- `1_risk_heatmap.png` - Grid risk value heatmap
- `2_resource_distribution.png` - Resource distribution map
- `3_protection_heatmap.png` - Protection level heatmap
- `4_convergence_curve.png` - DSSA convergence curve
- `5_terrain_map.png` - Terrain distribution map
- `6_time_dynamic_analysis.png` - Time-dynamic analysis plot
- `demo_results.json` - Complete results data
- `summary_report.txt` - Summary report

#### Batch Run Output (batch_run.py)
- `batch_output/{resource_type}/run_XXX/` - Run directories for each resource type
- `batch_output/batch_summary.json` - JSON summary report
- `batch_output/batch_summary.txt` - Text summary report

---

## marker/ - Image Viewer and Grid Marking Tool

### Overview

A standalone local image viewer and hexagonal grid marking tool for manual reserve grid marking.

### Core Files

| File | Function |
|------|----------|
| `image-viewer.html` | Complete HTML5 image viewer and grid marking tool |
| `grid-coordinates.json` | Pre-generated grid coordinate data example |

### Features

- Local image upload and preview
- Hexagonal grid generation and visualization
- 7 preset color marking system
- Zoom and pan functionality
- Grid selection (single, multiple, box selection)
- JSON/SVG data export

### Input & Output

#### Input
- Local image files
- JSON grid coordinate file (optional)

#### Output
- JSON format grid coordinates and marking data
- SVG format grid layer

---

## riskIndex/ - Protected Area Grid Risk Index Model

### Overview

Calculates risk coefficients for wildlife reserve grid cells to guide optimal allocation of patrol and monitoring resources.

### Core Modules

| File | Function |
|------|----------|
| `risk_model_wrapper.py` | JSON configuration-driven main API entry |
| `generate_hex_map.py` | Hexagonal grid map generator |
| `generate_square_map.py` | Square grid map generator |
| `visualize_risk_from_json.py` | Risk heatmap visualization tool |
| `convert_map_for_wrapper.py` | Map data format converter |
| `src/risk_model/` | Core risk model library |

### Module Structure

```
src/risk_model/
├── core/          # Core data structures (Grid, Species, Environment, TimeContext)
├── risk/          # Risk calculators
│   ├── human.py           # Human risk calculator
│   ├── environmental.py   | Environmental risk calculator
│   ├── density.py         # Species density risk calculator
│   ├── temporal.py        # Temporal factor calculator
│   └── composite.py       # Composite risk calculator
├── config/        # Configuration management (weights, defaults)
├── data/          # Data generation and I/O
├── visualization/ # Plotting and visualization
└── advanced/      # IMMC advanced features (DSSA, spatio-temporal risk field)
```

### Key Models & Formulas

#### 1. Human Risk (Distance-weighted)
```
Human risk = boundary_weight × distance_to_boundary_normalized
           + road_weight × distance_to_road_normalized
           + water_weight × distance_to_water_normalized
```

#### 2. Environmental Risk
```
Environmental risk = fire_weight × fire_risk
                   + terrain_weight × terrain_complexity
```

#### 3. Composite Risk (Normalized)
```
Raw risk = human_risk × human_weight
         + environmental_risk × environmental_weight
         + density_value × density_weight

Normalized risk = (raw_risk - min) / (max - min)
```

#### 4. Temporal Factors
```
Diurnal factor = sin(π × (hour - 6) / 12)  # Higher during day, lower at night

Seasonal factor = dry/rainy season adjustment coefficient

Temporal factor = diurnal × seasonal
```

### Key Parameters (Default Values)

#### Risk Weights (`RiskWeights`)
| Parameter | Default | Description |
|-----------|---------|-------------|
| `human_weight` | 0.4 | Human risk weight |
| `environmental_weight` | 0.3 | Environmental risk weight |
| `density_weight` | 0.3 | Species density weight |

#### Human Risk Weights (`HumanRiskWeights`)
| Parameter | Default | Description |
|-----------|---------|-------------|
| `boundary_weight` | 0.4 | Distance to boundary weight |
| `road_weight` | 0.35 | Distance to road weight |
| `water_weight` | 0.25 | Distance to water weight |

#### Environmental Risk Weights (`EnvironmentalRiskWeights`)
| Parameter | Default | Description |
|-----------|---------|-------------|
| `fire_weight` | 0.6 | Fire risk weight |
| `terrain_weight` | 0.4 | Terrain complexity weight |

### Input & Output

#### Input (risk_model_wrapper.py)
- `data.json` - Contains map configuration, grid data, time context
- `config.json` - Optional weight configuration file

#### Output
- `results.json` - Contains raw and normalized risk for each grid cell

#### Map Generator Output
- `hex_map_for_risk.json` / `square_map_for_risk.json` - Generated map data

---

## Quick Start

### hexdynamic - Single Optimization Run
```bash
cd hexdynamic
python demo.py
# Or use custom configuration
python demo.py my_config.json
```

### hexdynamic - Batch Run
```bash
cd hexdynamic
python batch_run.py --runs 10 --min 2 --range 4
```

### riskIndex - Risk Calculation
```bash
cd riskIndex
python risk_model_wrapper.py --data example_data.json --config example_config.json --output results.json
```

### riskIndex - Map Generation
```bash
cd riskIndex
python generate_hex_map.py
python generate_square_map.py
```

---

## Dependencies

All projects require:
- Python 3.7+
- numpy
- matplotlib

Install dependencies:
```bash
pip install -r requirements.txt
```
