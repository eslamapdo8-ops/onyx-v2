#!/usr/bin/env python3
"""Export MNIST 0/1 data as Verilog .hex files for V4 RTL testbench.
Reads MNIST from PNG directory (same format as onyx_v4_proto.py)."""
import numpy as np
import os, glob
from PIL import Image
from sklearn.linear_model import RidgeClassifier

def load_mnist_png_arrays(class_ids, n_per, split='testing', base='/workspaces/onyx-v2/mnist_png'):
    """Load MNIST as numpy arrays from PNG directories."""
    X, y = [], []
    for cid in class_ids:
        path = os.path.join(base, split, str(cid), '*.png')
        files = sorted(glob.glob(path))
        for f in files[:n_per]:
            img = Image.open(f).convert('L')  # grayscale
            arr = np.array(img, dtype=np.float64).flatten()
            X.append(arr)
            y.append(cid)
    X = np.array(X)
    y = np.array(y)
    return X, y

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
        self.seed = ((self.seed << 1) | fb) ^ (0xB4BCD35C if fb else 0)
        self.seed = self.seed & 0xFFFFFFFF  # عودة إلى 32-bit
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

# ── Load MNIST from PNG (25 zeros + 25 ones) ──
print('Loading MNIST from PNG...')
# Use fixed seed for reproducible load
np.random.seed(42)
X, y = load_mnist_png_arrays([0, 1], 100, 'training')
# Take exactly 25 per class in order (reproducible)
mask0 = np.where(y == 0)[0][:25]
mask1 = np.where(y == 1)[0][:25]
idx = np.concatenate([mask0, mask1])
X = X[idx]
y = y[idx]
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
fingerprints = np.zeros((len(features), 16), dtype=np.int32)
for s in range(len(features)):
    for d in range(16):
        ncos[d].reset()
        fw = int(features[s, d] * (2**30))
        for _ in range(20):
            ncos[d].step(fw)
        # fingerprint كمية: fire_count × (±1) بدلاً من ±1 فقط
        sign = 1 if ncos[d].firing_dir else -1
        fingerprints[s, d] = sign * ncos[d].fire_count

# ── Train Linear Readout ──
clf = RidgeClassifier(alpha=1.0)
clf.fit(fingerprints, y)
W = clf.coef_

# ── Write weights.hex ──
# Scale weights by SCALE_FACTOR so float values become meaningful 16-bit integers
# Ridge produces weights in [-1.5, 1.5]; multiply by 10000 preserves 4 decimal places
SCALE_FACTOR = 10000

# RidgeClassifier in binary mode returns coef_ of shape (n_features,)
# Build 2x16: class 0 = +coef, class 1 = -coef (mirror)
if W.ndim == 1:
    W_2d = np.stack([+W, -W], axis=0)  # (2, 16)
else:
    W_2d = W  # already (n_classes, n_features)

W_scaled = (W_2d * SCALE_FACTOR).astype(np.int64)

with open('weights_hex.txt', 'w') as f:
    for c in range(2):
        for d in range(16):
            val = int(W_scaled[c, d])
            if val < 0:
                val = val & 0xFFFF
            f.write(f'{val:04X} ')
        f.write('\n')
print(f'✓ weights_hex.txt (2×16, scaled by {SCALE_FACTOR})')

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
print(f'\n── Linear Readout Results (Python reference) ──')
print(f'Overall:     {correct}/{len(y)} = {correct/len(y)*100:.1f}%')
print(f'Class 0:     {c0_correct}/{c0_total} = {c0_correct/c0_total*100:.1f}%')
print(f'Class 1:     {c1_correct}/{c1_total} = {c1_correct/c1_total*100:.1f}%')
print(f'\nExpected in Verilog: ~{correct/len(y)*100:.1f}%')
