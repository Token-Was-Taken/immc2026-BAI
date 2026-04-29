#!/usr/bin/env python
"""Quick test to verify synergy parameters are loaded correctly."""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hexdynamic.protection_pipeline import build_data_loader
from hexdynamic.riskIndex.risk_model_wrapper import compute_risk_with_riskindex
import json

# Load base config
with open('hexdynamic/base1.json') as f:
    data = json.load(f)

# Compute risk
risk_map, tf_map, _ = compute_risk_with_riskindex(data)

# Build loader - this triggers coverage_params loading
loader = build_data_loader(data, risk_map, tf_map)

# Verify synergy params
print(f"alpha_pd = {loader.coverage_params.alpha_pd}")
print(f"alpha_pc = {loader.coverage_params.alpha_pc}")
print(f"Expected defaults: alpha_pd=0.4, alpha_pc=0.15")
assert loader.coverage_params.alpha_pd == 0.4, "alpha_pd default mismatch"
assert loader.coverage_params.alpha_pc == 0.15, "alpha_pc default mismatch"
print("✓ Synergy parameters loaded correctly")
