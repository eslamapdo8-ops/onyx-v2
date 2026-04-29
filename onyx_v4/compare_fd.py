#!/usr/bin/env python3
"""Compare Python NCO firing_dir vs Verilog output."""
import numpy as np

# Read features
with open('/workspaces/onyx-v2/onyx_v4/features_hex.txt') as f:
    lines = f.readlines()
features = np.zeros((50, 16), dtype=np.int64)
for s, line in enumerate(lines):
    vals = line.strip().split()
    for d, v in enumerate(vals):
        features[s, d] = int(v, 16)
features_s = np.where(features > 0x7FFFFFFF, features - 0x100000000, features)

class NCO:
    def __init__(self, th=0.5):
        self.acc = 0
        self.th = int(th * (2**30))
        self.off = int(0.25 * (2**30))
        self.fire_count = 0
        self.firing_dir = 0
        self.seed = 0xACE142BD
    def reset(self):
        self.acc = 0
        self.fire_count = 0
        self.seed = 0xACE142BD
    def step(self, fw):
        fb = self.seed & 1
        self.seed = ((self.seed << 1) | fb) ^ (0xB4BCD35C if fb else 0)
        self.seed = self.seed & 0xFFFFFFFF
        b0 = (self.seed >> 24) & 0xFF
        b1 = (self.seed >> 8) & 0xFF
        b2 = (self.seed << 8) & 0xFF0000
        b3 = (self.seed << 24) & 0xFF000000
        noise_s = (b0 | b1 | b2 | b3) >> 4
        if noise_s > 0x7FFFFFFF:
            noise_s -= 0x100000000
        self.acc = self.acc + fw + noise_s
        if self.acc > self.th:
            self.fire_count += 1
            self.firing_dir = 1
            self.acc -= self.off
        elif self.acc < -self.th:
            self.fire_count += 1
            self.firing_dir = 0
            self.acc += self.off

# Encode all 50 samples
py_fd = []
for s in range(50):
    ncos = [NCO(th=0.5*(1+0.3*(i/16))) for i in range(16)]
    fds = []
    for d in range(16):
        ncos[d].reset()
        for _ in range(3):
            ncos[d].step(features_s[s, d])
        fds.append(1 if ncos[d].firing_dir else 0)
    py_fd.append(fds)

print('Sample 0 firing_dir (Python):', ''.join(str(b) for b in py_fd[0]))
print('Sample 1:', ''.join(str(b) for b in py_fd[1]))
print('Sample 2:', ''.join(str(b) for b in py_fd[2]))

# Read weights
with open('/workspaces/onyx-v2/onyx_v4/weights_hex.txt') as f:
    wlines = f.readlines()
W = np.zeros((2, 16), dtype=np.int64)
for c, line in enumerate(wlines):
    vals = line.strip().split()
    for d, v in enumerate(vals):
        val = int(v, 16)
        W[c, d] = val if val < 0x8000 else val - 0x10000

print()
for s in range(3):
    fds = py_fd[s]
    score0 = sum(W[0, d] * (1 if fds[d] else -1) for d in range(16))
    score1 = sum(W[1, d] * (1 if fds[d] else -1) for d in range(16))
    print(f'Sample {s}: score0={score0}, score1={score1}, pred={0 if score0 > score1 else 1}')

correct = 0
y = np.array([0]*25 + [1]*25)
for s in range(50):
    fds = py_fd[s]
    score0 = sum(W[0, d] * (1 if fds[d] else -1) for d in range(16))
    score1 = sum(W[1, d] * (1 if fds[d] else -1) for d in range(16))
    pred = 0 if score0 > score1 else 1
    if pred == y[s]:
        correct += 1
print(f'\nPython NCO + Verilog weights = {correct}/50 = {correct*2:.0f}%')
