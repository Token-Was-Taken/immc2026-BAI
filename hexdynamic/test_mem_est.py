def est(num_grids, save_dpi):
    return max(80, int(num_grids * save_dpi / 10))

scenarios = [
    (24427, 80, "24K@80 (visualize-only default)"),
    (24427, 150, "24K@150"),
    (30000, 100, "30K@100"),
    (43758, 150, "43K@150 (user scenario)"),
    (43758, 80,  "43K@80 (suggested)"),
]
print(f"{'scenario':<32} {'MB/fig':>8} {'16GB->wrk':>11} {'8GB->wrk':>10}")
for ng, dpi, label in scenarios:
    e = est(ng, dpi)
    w16 = int(16000*0.5/e)
    w8  = int(8000*0.5/e)
    print(f"{label:<32} {e:>8} {w16:>11} {w8:>10}")
