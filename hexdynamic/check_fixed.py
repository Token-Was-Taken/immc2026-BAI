
import json

with open('test_out_fixed.json', 'r') as f:
    out_data = json.load(f)

print("=== Checking test_out_fixed.json ===")

# Check grid 58
found_58 = False
for grid in out_data['grids']:
    if grid['grid_id'] == 58:
        print(f"\nGrid 58:")
        print(f"  Has 'fences'? {'fences' in grid}")
        if 'fences' in grid:
            print(f"  Fences: {grid['fences']}")
        else:
            print("  NO FENCES!")
        found_58 = True
        break

if not found_58:
    print("\nGrid 58 not found!")

# Check grid 56
found_56 = False
for grid in out_data['grids']:
    if grid['grid_id'] == 56:
        print(f"\nGrid 56:")
        print(f"  Has 'fences'? {'fences' in grid}")
        if 'fences' in grid:
            print(f"  Fences: {grid['fences']}")
        found_56 = True
        break

# Check fitness history
print(f"\nFitness history len: {len(out_data['summary']['fitness_history'])}")
print(f"First 10 fitness values: {out_data['summary']['fitness_history'][:10]}")
print(f"Last 10 fitness values: {out_data['summary']['fitness_history'][-10:]}")
