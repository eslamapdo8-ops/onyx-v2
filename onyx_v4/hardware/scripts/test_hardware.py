#!/usr/bin/env python3
"""Test Onyx V4 on iCE40 hardware via UART.

Usage:
    python3 test_hardware.py [--port /dev/ttyUSB0] [--baud 115200]

Requires: pyserial
    pip3 install pyserial

Protocol (see ICE40_BRINGUP.md):
    Weight: 0xFE addr_hi addr_lo data_hi data_lo → ACK: 0xFF addr data_hi data_lo
    Classify: 0xFD + 64 bytes (16×32-bit LE features) → Result: 0xFC class fires_lo fires_hi + 8 bytes scores
"""

import serial
import sys
import os
import time
import struct

def read_hex_file(path):
    """Read features_hex.txt or weights_hex.txt as numpy-like arrays."""
    with open(path) as f:
        lines = f.readlines()
    if 'weights' in path:
        # weights_hex.txt: 2 lines × 16 hex values
        data = [[int(v, 16) for v in line.strip().split()] for line in lines]
        return data
    else:
        # features_hex.txt: 50 lines × 16 hex values
        data = [[int(v, 16) for v in line.strip().split()] for line in lines]
        return data

def to_signed_16(val):
    """Convert 16-bit unsigned to signed."""
    return val if val < 0x8000 else val - 0x10000

def to_signed_32(val):
    """Convert 32-bit unsigned to signed."""
    return val if val < 0x80000000 else val - 0x100000000

class OnyxV4ICE40:
    def __init__(self, port='/dev/ttyUSB0', baud=115200, timeout=2):
        self.ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(0.1)  # allow FPGA to initialize
        self.ser.reset_input_buffer()

    def load_weight(self, addr, data_signed):
        """Load a single 16-bit signed weight into the core."""
        # data_signed is [-32768, 32767]
        data_unsigned = data_signed & 0xFFFF
        cmd = struct.pack('<BBBH', 0xFE, addr, data_unsigned >> 8, data_unsigned & 0xFF)
        self.ser.write(cmd)
        # Read ACK: 0xFF addr data_hi data_lo
        ack = self.ser.read(4)
        if len(ack) != 4 or ack[0] != 0xFF:
            print(f"  WARNING: Weight ACK failed for addr {addr}: {ack.hex()}")
            return False
        return True

    def load_all_weights(self, weights_path):
        """Load all 32 weights (2 classes × 16 NCOs)."""
        weights = read_hex_file(weights_path)
        addr = 0
        for c in range(len(weights)):
            for d in range(len(weights[c])):
                val = to_signed_16(weights[c][d])
                self.load_weight(addr, val)
                addr += 1
        print(f"  Loaded {addr} weights")

    def classify(self, feature_row):
        """Send 16×32-bit features, return (class_id, total_fires, scores)."""
        # Pack 16×32-bit LE features
        cmd = struct.pack('<B', 0xFD)
        for f in feature_row:
            cmd += struct.pack('<I', f)
        self.ser.write(cmd)

        # Read result: 0xFC + class + fires_lo + fires_hi + 8 bytes scores
        res = self.ser.read(12)
        if len(res) != 12 or res[0] != 0xFC:
            print(f"  WARNING: Classify result failed: {res.hex() if res else 'empty'}")
            return None, None, None

        class_id = res[1]
        total_fires = res[2] | (res[3] << 8)
        score0 = struct.unpack('<i', res[4:8])[0]
        score1 = struct.unpack('<i', res[8:12])[0]

        return class_id, total_fires, (score0, score1)

    def close(self):
        self.ser.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Test Onyx V4 on iCE40')
    parser.add_argument('--port', default='/dev/ttyUSB0', help='Serial port')
    parser.add_argument('--baud', type=int, default=115200, help='Baud rate')
    args = parser.parse_args()

    # Determine paths (assume running from onyx_v4/ or hardware/)
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    features_path = os.path.join(base, 'features_hex.txt')
    weights_path = os.path.join(base, 'weights_hex.txt')
    labels_path = os.path.join(base, 'expected_labels.txt')

    if not all(os.path.exists(p) for p in [features_path, weights_path, labels_path]):
        print(f"ERROR: .hex files not found in {base}")
        print("Run 'python3 export_hex_data.py' first.")
        sys.exit(1)

    # Load expected labels
    with open(labels_path) as f:
        expected = [int(line.strip()) for line in f.readlines()]

    # Load features
    features = read_hex_file(features_path)

    print(f"Opening {args.port} at {args.baud} baud...")
    v4 = OnyxV4ICE40(args.port, args.baud)

    print("Loading weights...")
    v4.load_all_weights(weights_path)

    print(f"\nTesting {len(features)} samples...")
    correct = 0
    for s in range(len(features)):
        cls, fires, scores = v4.classify(features[s])
        if cls is None:
            print(f"  [{s}] SKIP (no response)")
            continue

        if cls == expected[s]:
            correct += 1
        else:
            print(f"  [{s}] expected={expected[s]}, got={cls}, fires={fires}, scores=({scores[0]},{scores[1]})")

        time.sleep(0.01)  # small delay between samples

    v4.close()

    print(f"\n{'='*50}")
    print(f"  Final: {correct}/{len(features)} = {correct/len(features)*100:.1f}%")
    print(f"  Expected (simulation): ~72%")
    print(f"{'='*50}")


if __name__ == '__main__':
    main()
