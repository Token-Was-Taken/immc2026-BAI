
import json
from protection_pipeline import load_input, build_data_loader, VectorizedCoverageModel, DSSAConfig, DSSAOptimizer, compute_risk_with_riskindex

# Run a quick test with max_iterations = 1
print("=== Running debug test ===")

# Load input
data = load_input('base1.json')
data['dssa_config']['max_iterations'] = 1  # Quick test
data['dssa_config']['population_size'] = 5

# Compute risk
risk_map, temporal_factor_map, raw_risk_map = compute_risk_with_riskindex(data)

# Build data loader
loader = build_data_loader(data, risk_map, temporal_factor_map)
grid_model = HexGridModel(loader.grids)

# Let's check the deployment matrix for grid 58
print("\n=== Checking deployment matrix for grid 58 ===")
print(f"  grid 58 in camera deployment: {loader.deployment_matrix.get('camera', {}).get(58, 'not in dict')}")
print(f"  grid 58 in drone deployment: {loader.deployment_matrix.get('drone', {}).get(58, 'not in dict')}")
print(f"  grid 58 in camp deployment: {loader.deployment_matrix.get('camp', {}).get(58, 'not in dict')}")
print(f"  grid 58 in fence deployment: {loader.deployment_matrix.get('fence', {}).get(58, 'not in dict')}")

# Let's check what boundary edges are available for grid 58
print("\n=== Checking boundary edges for grid 58 ===")
try:
    from hexagon_tools import HexagonTools
    ht = HexagonTools()
    boundary_edges = ht.get_boundary_edges_for_grid(58, grid_model)
    print(f"  Boundary edges for grid 58: {boundary_edges}")
except Exception as e:
    print(f"  Error: {e}")

# Let's also check neighboring grid 56
print("\n=== Checking deployment matrix for grid 56 ===")
print(f"  grid 56 in fence deployment: {loader.deployment_matrix.get('fence', {}).get(56, 'not in dict')}")

# Let's see what grids are in fence deployment
print("\n=== Checking grids in fence deployment ===")
fence_grids = [gid for gid, val in loader.deployment_matrix.get('fence', {}).items() if val == 1]
print(f"  Number of grids in fence deployment: {len(fence_grids)}")
if 58 in fence_grids:
    print(f"  ✓ Grid 58 is in fence deployment")
else:
    print(f"  ✗ Grid 58 is NOT in fence deployment!")

print("\n=== Done ===")
