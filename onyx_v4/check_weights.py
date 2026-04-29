#!/usr/bin/env python3
"""Compare weights from file vs what Verilog sees."""
import numpy as np

with open('/workspaces/onyx-v2/onyx_v4/weights_hex.txt') as f:
    lines = f.readlines()
W = np.zeros((2, 16), dtype=np.int64)
for c, line in enumerate(lines):
    vals = line.strip().split()
    for d, v in enumerate(vals):
        val = int(v, 16)
        W[c, d] = val if val < 0x8000 else val - 0x10000

print('W class0 sum:', W[0].sum())
print('W class1 sum:', W[1].sum())
print('W[0]:', W[0])
print('W[1]:', W[1])

print()
print('All firing_dir=1:')
print('  score0 =', W[0].sum(), ' score1 =', W[1].sum())
print('All firing_dir=0:')
print('  score0 =', -W[0].sum(), ' score1 =', -W[1].sum())

# Read features and compute firing_dir
with open('/workspaces/onyx-v2/onyx_v4/features_hex.txt') as f:
    flines = f.readlines()
features = np.zeros((len(flines), 16), dtype=np.int64)
for s, line in enumerate(flines):
    vals = line.strip().split()
    for d, v in enumerate(vals):
        features[s, d] = int(v, 16)
features_s = np.where(features > 0x7FFFFFFF, features - 0x100000000, features)

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

print()
print('Sample 0:')
ncos = [NCO(th=0.5*(1+0.3*(i/16))) for i in range(16)]
for d in range(16):
    ncos[d].reset()
    for _ in range(3):
        ddir = ncos[d].step(features_s[0, d])

fds = []
for d in range(16):
    fd = 1 if ncos[d].firing_dir else 0
    fds.append(fd)
print('  firing_dir:', fds)
print('  sum(fd):', sum(fds))
score_py_0 = sum(W[0, d] * (1 if fds[d] else -1) for d in range(16))
score_py_1 = sum(W[1, d] * (1 if fds[d] else -1) for d in range(16))
print('  scores (Python):', score_py_0, score_py_1)
print('  argmax:', 0 if score_py_0 > score_py_1 else 1)
