#!/usr/bin/env python3
"""Diagnose firing_dir patterns on real features."""
import numpy as np

class NCO:
    def __init__(self, th=0.5):
        self.acc = 0
        self.th = int(th * (2**30))
        self.off = int(0.25 * (2**30))
        self.seed = 0xACE142BD
    def reset(self):
        self.acc = 0
        self.seed = 0xACE142BD
    def step(self, fw):
        fb = self.seed & 1
        self.seed = ((self.seed >> 1) | (fb << 31)) ^ (0xB4BCD35C if fb else 0)
        b0 = (self.seed >> 24) & 0xFF; b1 = (self.seed >> 8) & 0xFF
        b2 = (self.seed << 8) & 0xFF0000; b3 = (self.seed << 24) & 0xFF000000
        noise_s = (b0 | b1 | b2 | b3) >> 4
        self.acc = self.acc + fw + noise_s
        if self.acc > self.th:
            self.acc -= self.off
            return 1
        elif self.acc < -self.th:
            self.acc += self.off
            return -1
        return None

# Load features
with open('/workspaces/onyx-v2/onyx_v4/features_hex.txt') as f:
    lines = f.readlines()
features = np.zeros((len(lines), 16), dtype=np.int64)
for s, line in enumerate(lines):
    vals = line.strip().split()
    for d, v in enumerate(vals):
        features[s, d] = int(v, 16)
features_s = np.where(features > 0x7FFFFFFF, features - 0x100000000, features)

# Check firing_dir statistics
all_fds = np.zeros((50, 16), dtype=np.int8)
for s in range(50):
    ncos = [NCO(th=0.5*(1+0.3*(i/16))) for i in range(16)]
    for d in range(16):
        ncos[d].reset()
        last_dir = 0
        for _ in range(3):
            ddir = ncos[d].step(features_s[s, d])
            if ddir is not None:
                last_dir = 1 if ddir == 1 else 0
        all_fds[s, d] = last_dir

print('Firing_dir stats:')
print(f'  Mean across all 50x16: {all_fds.mean():.3f}')
print(f'  Per sample mean (first 10): {[all_fds[s].mean() for s in range(10)]}')
print(f'  Per dimension mean: {[all_fds[:,d].mean() for d in range(16)]}')

# Also compute what scores should be
with open('/workspaces/onyx-v2/onyx_v4/weights_hex.txt') as f:
    wlines = f.readlines()
W = np.zeros((2, 16), dtype=np.int64)
for c, line in enumerate(wlines):
    vals = line.strip().split()
    for d, v in enumerate(vals):
        val = int(v, 16)
        W[c, d] = val if val < 0x8000 else val - 0x10000

print(f'\nWeights range: {W.min()} to {W.max()}')
print(f'  Class0 sum: {W[0].sum()}, Class1 sum: {W[1].sum()}')

# Compute scores in Python
y = np.array([0]*25 + [1]*25)
fingerprints = np.where(all_fds == 1, 1, -1)
scores = W @ fingerprints.T  # (2, 50)
preds = np.argmax(scores, axis=0)
print(f'\nPython Linear Readout on real features:')
print(f'  Matches Python reference: {np.sum(preds == y)}/50 = {np.mean(preds == y)*100:.1f}%')

# Show first mismatch detail
for s in range(50):
    if preds[s] != y[s]:
        print(f'\nMismatch sample {s}: expected={y[s]}, got={preds[s]}')
        print(f'  scores: [{scores[0,s]}, {scores[1,s]}]')
        print(f'  firing_dir (first 5): {all_fds[s,:5]}')
        break
