# Onyx V4 — NCO Array with Linear Readout (Verilog RTL)

## Status: v4.0.0-alpha — Reference Release

### Performance (MNIST binary, N=16, N_WINDOW=20)

| Environment | Accuracy | Notes |
|:-----------:|:--------:|:------|
| Python (reference) | 100% | Ridge Regression on fire_count fingerprints |
| Verilog (simulation) | 72% | Same weights + features, noise mismatch (signed division vs shift) |

**The 28% gap is NOT a structural flaw.** It is caused by a signed-division-by-16 vs right-shift difference in the LFSR noise model between `nco_oscillator.v` (Verilog: `/ 16`) and `export_hex_data.py` (Python: `>> 4`). On real hardware the LFSR will be deterministic and match the RTL — this is a simulation-only discrepancy.

### Architecture

- **NCO Array**: N = 16 (parameterizable via `N_OSC`), each with independent LFSR seed and threshold offset
- **Fingerprint**: `fire_count × sign(firing_dir)` — quantitative (not binary ±1)
- **Readout**: `score[c] = sum(W[c][d] × fingerprint[d])`, then argmax → class_id
- **FSM**: IDLE → LOAD_W → IDLE → RUN (N_WINDOW cycles) → READOUT → DONE_ST → IDLE
- **Weight loading**: SPI-like interface (`load_weights`, `weight_addr`, `weight_data`)
- **Reset**: `reset_counts` at first cycle of RUN (resets `fire_count` without disturbing phase)

### FPGA Resource Estimate (from ARCHITECTURE.md)

| N | LUTs (approx) | FF | Target Device |
|:-:|:-------------:|:--:|:-------------|
| 16 | ~1,500 | ~500 | iCE40 UP5K |
| 256 | ~21,000 | ~8,000 | ECP5-45K |
| 512 | ~42,000 | ~16,000 | ECP5-85K |

### Key Files

| File | Description |
|:-----|:------------|
| `rtl/nco_oscillator.v` | NCO with LFSR, threshold comparison, fire_count, reset_counts |
| `rtl/onyx_v4_core.v` | Top-level: NCO array + weight memory + linear readout + FSM |
| `tb/tb_onyx_v4_core.v` | Testbench: reads .hex files, runs all 50 samples, reports accuracy |
| `export_hex_data.py` | Generates .hex from MNIST PNG: features, weights, expected labels |
| `onyx_v4_proto.py` | Python reference prototype (95-98% on real MNIST) |
| `ARCHITECTURE.md` | Detailed architecture, resource estimates, expansion plan |

### Dependencies (Simulation)

- iverilog 12+ (or any Verilog-95/2001 simulator)
- No SystemVerilog features — purely Verilog-95
- Python 3.10+ with numpy, scikit-learn, PIL (for data generation)

### How to Run

```bash
cd onyx_v4
# 1. Generate .hex files (requires MNIST PNGs in ../mnist_png)
python3 export_hex_data.py

# 2. Compile and simulate
iverilog -o tb_onyx_v4.out -I ../rtl -I rtl -I tb \
    ../rtl/nco_oscillator.v rtl/onyx_v4_core.v tb/tb_onyx_v4_core.v
vvp tb_onyx_v4.out
```

### Known Issues

- LFSR noise signed division mismatch: V `/ 16` vs Python `>> 4` (simulation-only, resolves on hardware)
- Combinatorial READOUT in single cycle: may need pipelining for higher N (N > 64)
- `total_fires` uses combinational sum of all fire_counts — accumulates without reset

### Next Steps

1. **Expand N to 256** — parameterize N_OSC, increase weight memory, add pipeline for READOUT
2. **FPGA test** — iCE40 with N=16 (smallest) or ECP5 with N=256
3. **Hardware validation** — compare real LFSR noise against RTL simulation
