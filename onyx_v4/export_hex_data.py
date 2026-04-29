#!/usr/bin/env python3
"""Export MNIST 0/1 data as Verilog .hex files for V4 RTL testbench.
Works without TensorFlow — reads MNIST from gzip files directly."""
import numpy as np
import gzip
import os

MNIST_DIR = os.path.join(os.path.dirname(__file__), '..', 'HD_NCO_ARRAY', 'mnist_data')

def read_mnist_images(filename):
    """Read MNIST images from IDX3 format."""
    with gzip.open(filename, 'rb') as f:
        f.read(16)  # magic + dims
        data = np.frombuffer(f.read(), dtype=np.uint8)
    return data.reshape(-1, 784).astype(np.float64)

def read_mnist_labels(filename):
    """Read MNIST labels from IDX1 format."""
    with gzip.open(filename, 'rb') as f:
        f.read(8)  # magic + count
        return np.frombuffer(f.read(), dtype=np.uint8)

def to_fixed(x):
    """Convert float ∈ [-1,1] to signed 32-bit hex (Q1.30 format)."""
    raw = int(x * (2**30))
    return raw & 0xFFFFFFFF if raw < 0 else raw

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
    def step(self, f_word):
        fb = self.seed & 1
        self.seed = ((self.seed >> 1) | (fb << 31)) ^ (0xB4BCD35C if fb else 0)
        b0 = (self.seed >> 24) & 0xFF
        b1 = (self.seed >> 8) & 0xFF
        b2 = (self.seed << 8) & 0xFF0000
        b3 = (self.seed << 24) & 0xFF000000
        noise_s = (b0 | b1 | b2 | b3) >> 4
        self.acc = self.acc + f_word + noise_s
        if self.acc > self.th:
            self.fire_count += 1
            self.firing_dir = 1
            self.acc -= self.off
        elif self.acc < -self.th:
            self.fire_count += 1
            self.firing_dir = 0
            self.acc += self.off

# ── Load MNIST from gzip ──
print(f'Looking for MNIST in: {MNIST_DIR}')
if not os.path.isdir(MNIST_DIR):
    # Try fallback paths
    for p in ['/workspaces/onyx-v2/HD_NCO_ARRAY/mnist_data',
              os.path.join(os.path.dirname(__file__), 'mnist_data')]:
        if os.path.isdir(p):
            MNIST_DIR = p
            break
    else:
        print('ERROR: mnist_data directory not found!')
        print('Looked in:')
        print(f'  {os.path.join(os.path.dirname(__file__), "..", "HD_NCO_ARRAY", "mnist_data")}')
        import sys; sys.exit(1)

print(f'Using MNIST from: {MNIST_DIR}')

xt = read_mnist_images(os.path.join(MNIST_DIR, 'train-images-idx3-ubyte.gz'))
yt = read_mnist_labels(os.path.join(MNIST_DIR, 'train-labels-idx1-ubyte.gz'))

mask = (yt == 0) | (yt == 1)
X = xt[mask][:50]
y = yt[mask][:50]
print(f'Total: {len(X)}, class 0: {sum(y==0)}, class 1: {sum(y==1)}')

# ── Random Projection 784→16 ──
np.random.seed(42)
proj = np.random.randn(784, 16).astype(np.float64)
proj /= np.linalg.norm(proj, axis=0, keepdims=True)
features = X @ proj
scale = np.max(np.abs(features))
features = features / scale * 0.5

# ── Write features.hex ──
with open('features_hex.txt', 'w') as f:
    for s in range(len(features)):
        for d in range(16):
            f.write(f'{to_fixed(features[s,d]):08X} ')
        f.write('\n')
print('✓ features_hex.txt (50×16)')

# ── NCO encode ──
ncos = [NCO(th=0.5 * (1 + 0.3 * (i / 16))) for i in range(16)]
fingerprints = np.zeros((len(features), 16), dtype=np.int8)
for s in range(len(features)):
    for d in range(16):
        ncos[d].reset()
        fw = int(features[s, d] * (2**30))
        for _ in range(3):
            ncos[d].step(fw)
        fingerprints[s, d] = 1 if ncos[d].firing_dir else -1

# ── Train Linear Readout ──
from sklearn.linear_model import RidgeClassifier
clf = RidgeClassifier(alpha=1.0)
clf.fit(fingerprints, y)
W = clf.coef_

# ── Write weights.hex ──
with open('weights_hex.txt', 'w') as f:
    for c in range(2):
        for d in range(16):
            val = int(W[c, d])
            if val < 0:
                val = val & 0xFFFF
            f.write(f'{val:04X} ')
        f.write('\n')
print('✓ weights_hex.txt (2×16)')

# ── Write expected_labels.txt ──
with open('expected_labels.txt', 'w') as f:
    for lbl in y:
        f.write(f'{lbl}\n')
print('✓ expected_labels.txt')

# ── Report ──
preds = clf.predict(fingerprints)
correct = np.sum(preds == y)
c0_correct = np.sum((preds == y) & (y == 0))
c1_correct = np.sum((preds == y) & (y == 1))
c0_total = np.sum(y == 0)
c1_total = np.sum(y == 1)
print(f'\n── Training Results ──')
print(f'Overall: {correct}/{len(y)} = {correct/len(y)*100:.1f}%')
print(f'Class 0: {c0_correct}/{c0_total} = {c0_correct/c0_total*100:.1f}%')
print(f'Class 1: {c1_correct}/{c1_total} = {c1_correct/c1_total*100:.1f}%')
