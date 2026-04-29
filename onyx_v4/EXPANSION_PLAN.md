# Onyx V4 — Expansion Plan: N=16 → N=256 (and beyond)

## Goal

Scale the proven NCO Array + Linear Readout architecture from N=16 to N=256,
targeting ECP5-45K (~21K LUTs, ~8K FFs).

## Changes Required

### 1. `onyx_v4_core.v` — Parameterization (easy)

```verilog
// Change the default:
parameter N_OSC = 256;  // was 16
```

The `generate` loop already scales. `wire [N_OSC*ACC_WIDTH-1:0] osc_fire_counts` grows
from 512 bits to 8,192 bits — still fine for synthesis.

### 2. Weight Memory — 256×10 weights (moderate)

- Binary: 512 weights (2 × 256) = 1,024 bytes
- 10-class: 2,560 weights (10 × 256) = 5,120 bytes
- Use block RAM (ECP5 has up to 360Kb BRAM → 45KB)
- Address width: `$clog2(N_CLASSES * N_OSC)` → 12 bits for 10×256

### 3. READOUT — Pipeline (critical)

Current single-cycle READOUT works at N=16 but will fail timing at N=256:

```verilog
// Current (combinatorial — 256×10 = 2,560 adds in one cycle)
for (c=0; c<N_CLASSES; c++)
    for (d=0; d<N_OSC; d++)
        scores[c] += weight[c][d] + fire_count[d];

// Proposed (pipelined):
// Stage 1: partial = weight[d] × fire_count[d]
// Stage 2: tree_adder across N_OSC
// Stage 3: scores[c] + valid
```

Estimated pipeline depth: 3-4 cycles (vs 1 cycle currently).

### 4. Resource Estimate (Updated)

| Component | N=16 | N=256 | Notes |
|:----------|:----:|:-----:|:------|
| NCOs | 16 | 256 | `nco_oscillator` × 256 |
| LFSR | 16×32b | 256×32b | 8Kb LFSR state |
| Accumulators | 16×32b | 256×32b | 8Kb ACC |
| Weight memory | 32×16b | 5,120×16b | BRAM, not LUTs |
| READOUT tree | 16→1 | 256→1 | Needs pipeline |
| **Total LUTs** | **~1,500** | **~21,000** | ECP5-45K limit: 44K |
| **Total FFs** | **~500** | **~8,000** | ECP5-45K limit: 44K |

### 5. Timing

- ECP5-45K: 48 MHz typical, -12 speed grade → ~20ns cycle
- NCO accumulator + comparator: ~8ns (critical)
- READOUT tree adder (256→1): ~6ns with pipeline, ~35ns without
- **Pipeline essential** for READOUT at N=256

## Implementation Order

### Phase A: N=64 (quick validation)
1. Set N_OSC=64, N_CLASSES=2
2. Verify compilation + simulation with 50 MNIST samples
3. Check resource usage with Yosys (expect ~4K LUTs)

### Phase B: N=256 with pipelined READOUT
1. Add pipeline registers between READOUT stages
2. Set N_OSC=256, N_CLASSES=2
3. Verify compilation + simulation
4. Yosys synthesis report

### Phase C: Multi-class (N_CLASSES=10)
1. Set N_CLASSES=10
2. Increase weight memory to 2,560
3. Re-train Ridge with 10 classes in Python
4. Verify with 100 MNIST samples (all 10 classes)

## FPGA Board Options

| Board | Device | LUTs | BRAM | Price | Viability |
|:------|:-------|:----:|:----:|:-----:|:----------|
| iCEBreaker | iCE40 UP5K | 5.3K | 128Kb | ~$50 | N=16 only |
| ULX3S (v3.0.2) | ECP5-12F | 12K | 288Kb | ~$90 | N=128 max |
| **ULX3S (v3.0.2)** | **ECP5-45F** | **44K** | **360Kb** | **~$110** | **N=256 ✓** |
| Radiona ULX3S | ECP5-85F | 83K | 360Kb | ~$130 | N=512+ |

**Recommended:** ULX3S with ECP5-45F (best cost/capacity ratio for N=256)
