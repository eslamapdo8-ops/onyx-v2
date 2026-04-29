# Onyx V4 — iCE40 UP5K Bring-up Plan

## Goal

Implement Onyx V4 (N=16, binary classification) on iCE40 UP5K (iCEBreaker board)
as **proof-of-concept** for the NCO Array + Linear Readout architecture on real hardware.

## Board: iCEBreaker v1.2

- **FPGA:** iCE40 UP5K (5,280 LUTs, 128Kb BRAM)
- **Clock:** 12 MHz (on-board oscillator)
- **I/O:** 2× PMOD, 8× LEDs, 2× buttons, USB-UART
- **Price:** ~$50
- **Toolchain:** Yosys + nextpnr-ice40 + icepack

## Resource Usage (N=16)

| Component | LUTs | FFs | BRAM (bits) |
|:----------|:----:|:---:|:-----------:|
| 16× NCO oscillators | ~1,280 | ~512 | 0 |
| 1× FSM (IDLE→LOAD→RUN→READOUT→DONE) | ~50 | ~20 | 0 |
| 1× Weight memory (32×16b) | 0 | 0 | 512 |
| 1× READOUT (2×16 adders + argmax) | ~150 | ~32 | 0 |
| 1× UART receiver (115200 baud) | ~100 | ~50 | 0 |
| **Total (estimate)** | **~1,580** | **~614** | **512** |

*Fits easily within iCE40 UP5K (5,280 LUTs).*

## Block Diagram

```
┌─────────────────────────────────────────────┐
│                   onyx_v4_ice40              │
│  ┌──────────┐    ┌──────────────────────┐   │
│  │ UART Rx  │───→│  Weight Loader        │   │
│  │ 115200   │    │  (writes weight_mem)  │   │
│  └──────────┘    └──────────┬───────────┘   │
│                             │                │
│  ┌──────────┐    ┌──────────▼───────────┐   │
│  │ Feature  │───→│   NCO Array x16      │   │
│  │ Buffer   │    │   (parallel encode)  │   │
│  │ (32b×16) │    └──────────┬───────────┘   │
│  └──────────┘               │                │
│                    ┌────────▼───────────┐   │
│                    │   Linear Readout   │   │
│                    │  (score → argmax)  │   │
│                    └────────┬───────────┘   │
│                             │                │
│                    ┌────────▼───────────┐   │
│                    │  UART Tx (result)  │   │
│                    └────────────────────┘   │
└─────────────────────────────────────────────┘
```

## Communication Protocol (UART 115200)

### Weight Loading (host → FPGA)
```
Byte 0: 0xFE (header)
Byte 1: weight_addr (0..31)
Byte 2: weight_data high byte (signed 16-bit)
Byte 3: weight_data low byte
FPGA echoes: 0xFF, addr, data_high, data_low (ack)
```

### Classification Request (host → FPGA)
```
Byte 0: 0xFD (classify header)
Bytes 1-64: 16× 32-bit features (little-endian)
FPGA processes, then responds:
Byte 0: 0xFC (result header)
Byte 1: class_id (0 or 1)
Bytes 2-3: total_fires (16-bit)
Bytes 4-7: score[0] (32-bit signed LE)
Bytes 8-11: score[1] (32-bit signed LE)
```

## File Structure

```
onyx_v4/hardware/
├── ice40/
│   ├── onyx_v4_ice40.v      # Top-level: UART + core + clocking
│   ├── uart_rx.v            # UART receiver (115200, 8N1)
│   ├── uart_tx.v            # UART transmitter
│   └── onyx_v4_ice40.pcf    # Pin constraints for iCEBreaker
├── build/
│   └── Makefile             # Yosys + nextpnr + icepack
└── scripts/
    └── test_hardware.py     # Python script: load weights + classify via UART
```

## Bring-up Steps

### 1. Toolchain Setup
```bash
# Install OSS CAD Suite (or use pre-built binaries)
wget https://github.com/YosysHQ/oss-cad-suite-build/releases/latest/download/oss-cad-suite-linux-x64.tgz
tar -xzf oss-cad-suite-linux-x64.tgz
export PATH="$PWD/oss-cad-suite/bin:$PATH"

# Verify
yosys -V        # Should show 0.40+
nextpnr-ice40 -h  # Should show help
icepack -V      # Should show version
```

### 2. Build bitstream
```bash
cd onyx_v4/hardware/build
make           # runs yosys → nextpnr → icepack → onyx_v4_ice40.bin
```

### 3. Flash to board
```bash
# Using iceprog (if connected via FTDI)
iceprog onyx_v4_ice40.bin

# Or using openFPGALoader
openFPGALoader -b iceBreaker onyx_v4_ice40.bin
```

### 4. Test with Python
```bash
python3 onyx_v4/hardware/scripts/test_hardware.py
# Loads weights_hex.txt, sends features from features_hex.txt via UART,
# compares class_id against expected_labels.txt
```

## RTL Modifications Needed

### New Files
- `onyx_v4_ice40.v` — Top-level: instantiates `onyx_v4_core`, UART, clock divider
- `uart_rx.v` — Simple UART receiver (no CTS/RTS)
- `uart_tx.v` — Simple UART transmitter

### Core Modifications (minor)
- Add `features_in` shift register (UART feeds 16×32b sequentially)
- Add `result_valid` + `result_class_id` + `result_scores` for UART readout
- FSM already supports LOAD_W and START — no change needed

## Test Procedure

1. Program FPGA with `onyx_v4_ice40.bin`
2. Connect USB-UART (115200, 8N1, no flow control)
3. Run `test_hardware.py`:
   - Loads 32 weights (class 0 + class 1)
   - Sends all 50 MNIST feature vectors one by one
   - Collects class_id + scores + total_fires for each
   - Reports accuracy (should match 72% from simulation)
4. Verify with oscilloscope/logic analyzer:
   - Check LFSR output on GPIO (optional)
   - Check `done` pulse width
   - Measure classification latency (~20 cycles × 12 MHz = 1.67µs)

## Known Limitations (iCE40)

- No block RAM for feature storage — features sent one-by-one via UART
- No on-chip MNIST database — host PC sends images
- N=16 only (iCE40 insufficient for N=256)
- LFSR noise may differ slightly from Python (see README)

## After Proof-of-Concept

Once N=16 works on iCE40:
1. Order ULX3S (ECP5-45F, ~$110)
2. Port to ECP5: only pin constraints + clock divider change
3. Expand to N=256 using `generate` loop (already tested in simulation)
4. Add on-chip BRAM for weight storage (no UART needed for weights)
