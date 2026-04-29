#!/usr/bin/env python3
"""
Onyx V4.1 — Hybrid CNN + NCO Array
====================================
التصميم:
  - Conv2D (3x3, 8 filters) + ReLU + MaxPool (2x2)
  - Conv2D (3x3, 16 filters) + ReLU + MaxPool (2x2)  → 7x7x16 = 784 features
  - FC layer: 784 → 128 features (no activation)
  - NCO Array (N=256) on extracted features
  - Linear Readout for final classification

الهدف: ≥85% على MNIST 10 فئات.
"""

import os, sys, math, time, random
import numpy as np
from PIL import Image

SEP = '=' * 72
MNIST_PATH = "/workspaces/onyx-v2/mnist_png"

# NNCO parame ers (same as V4)
TH = 2**30
OFFSET = TH // 2
F_WORD = 2**28
THS = np.array([int(TH * (0.8 + 0.4 * i / 6)) for i in range(6)])
OFFSETS = THS // 2


class NCO:
    __slots__ = ('acc', 'th', 'offset', 'firing_dir', 'fire_count', 'seed')
    def __init__(self, th, offset, seed):
        self.acc = 0
        self.th = th
        self.offset = offset
        self.firing_dir = 0
        self.fire_count = 0
        self.seed = seed

    def reset(self):
        self.acc = 0
        self.firing_dir = 0
        self.fire_count = 0

    def step(self, drive, n_steps=3):
        for _ in range(n_steps):
            rng = np.random.RandomState(self.seed + _ + self.fire_count)
            noise = int(rng.randint(-TH // 8, TH // 8))
            self.acc += int(drive) + noise
            if self.acc > self.th:
                self.firing_dir = 1
                self.fire_count += 1
                self.acc -= self.offset
            elif self.acc < -self.th:
                self.firing_dir = -1
                self.fire_count += 1
                self.acc += self.offset


# ========== Pure NumPy CNN ==========
def im2col(img, ksize=3, stride=1, pad=1):
    """Convert image to column matrix for efficient convolution."""
    C, H, W = img.shape
    H_out = (H + 2*pad - ksize) // stride + 1
    W_out = (W + 2*pad - ksize) // stride + 1
    img_pad = np.pad(img, ((0,0), (pad,pad), (pad,pad)), mode='constant')

    cols = np.zeros((C, ksize, ksize, H_out, W_out))
    for h in range(H_out):
        for w in range(W_out):
            cols[:, :, :, h, w] = img_pad[:, h*stride:h*stride+ksize,
                                            w*stride:w*stride+ksize]
    cols = cols.transpose(1, 2, 0, 3, 4).reshape(ksize*ksize*C, H_out*W_out)
    return cols


def conv2d_forward(x, W, b):
    """x: (N, C, H, W), W: (F, C, 3, 3), b: (F,) → (N, F, H', W')."""
    N, C, H, W = x.shape
    F, _, ksize, _ = W.shape
    stride = 1
    pad = 1
    H_out = (H + 2*pad - ksize) // stride + 1
    W_out = (W + 2*pad - ksize) // stride + 1

    out = np.zeros((N, F, H_out, W_out))
    for n in range(N):
        cols = im2col(x[n], ksize, stride, pad)  # (C*9, H'*W')
        W_flat = W.reshape(F, -1)                 # (F, C*9)
        out[n] = (W_flat @ cols + b[:, None]).reshape(F, H_out, W_out)
    return np.maximum(out, 0)  # ReLU


def maxpool2x2(x):
    """x: (N, C, H, W) → (N, C, H//2, W//2)."""
    N, C, H, W = x.shape
    x_r = x.reshape(N, C, H//2, 2, W//2, 2)
    return x_r.max(axis=(3, 5))


def flatten(x):
    """x: (N, C, H, W) → (N, C*H*W)."""
    return x.reshape(x.shape[0], -1)


def build_cnn():
    """Build CNN weights and return forward function."""
    # Conv1: 1 → 8 filters, 3x3
    W1 = np.random.randn(8, 1, 3, 3) * np.sqrt(2.0 / (1 * 9))
    b1 = np.zeros(8)
    # Conv2: 8 → 16 filters, 3x3
    W2 = np.random.randn(16, 8, 3, 3) * np.sqrt(2.0 / (8 * 9))
    b2 = np.zeros(16)
    # FC: 784 (7*7*16) → 128
    W3 = np.random.randn(128, 784) * np.sqrt(2.0 / 784)
    b3 = np.zeros(128)

    def forward(images_np):
        """images_np: (N, 28, 28) → features: (N, 128)."""
        x = images_np[:, None, :, :].astype(np.float32)  # (N, 1, 28, 28)
        x = x / 127.5 - 1.0  # normalize to [-1, 1]

        # Conv1 + ReLU + Pool
        x = conv2d_forward(x, W1, b1)  # (N, 8, 28, 28)
        x = maxpool2x2(x)              # (N, 8, 14, 14)

        # Conv2 + ReLU + Pool
        x = conv2d_forward(x, W2, b2)  # (N, 16, 14, 14)
        x = maxpool2x2(x)              # (N, 16, 7, 7)

        # Flatten + FC
        x = flatten(x)                 # (N, 784)
        x = x @ W3.T + b3              # (N, 128) — no activation
        return x

    return forward


# ========== Load MNIST ==========
def load_mnist(class_ids, n_per, split='testing'):
    images, labels = [], []
    for cls in class_ids:
        cls_dir = os.path.join(MNIST_PATH, split, str(cls))
        files = sorted(os.listdir(cls_dir))[:n_per]
        for fname in files:
            img = Image.open(os.path.join(cls_dir, fname)).convert('L')
            arr = np.array(img, dtype=np.uint8)
            images.append(arr)
            labels.append(cls)
    return np.array(images), np.array(labels)


# ========== NCO Encoding ==========
def encode_nco_array(features, ncos, n_steps=3, noise_seed=42):
    """Encode CNN features into NCO fingerprints. features: (N, D)."""
    N, D = features.shape
    fingerprints = np.zeros((N, D), dtype=np.int8)
    np.random.seed(noise_seed)

    for s in range(N):
        if s % 500 == 0 and s > 0:
            print(f"    encoded {s}/{N}", file=sys.stderr)
        f = features[s]
        scale = TH * 0.3 / max(np.abs(f).max(), 1.0)

        for d in range(D):
            ncos[d].reset()
            drive = int(f[d] * scale)
            ncos[d].step(drive, n_steps)
            fingerprints[s, d] = ncos[d].firing_dir

    return fingerprints


# ========== Linear Readout ==========
def train_linear_readout(fingerprints, labels, class_ids, lam=1.0):
    """Ridge regression: W = Y @ F^T @ (F @ F^T + λI)^-1."""
    n_classes = len(class_ids)
    n_samples = fingerprints.shape[0]
    n_dims = fingerprints.shape[1]

    label_to_idx = {c: i for i, c in enumerate(class_ids)}
    Y = np.zeros((n_samples, n_classes))
    for i, lbl in enumerate(labels):
        Y[i, label_to_idx[lbl]] = 1.0

    F = fingerprints.astype(np.float64)

    if n_dims <= n_samples:
        W = np.linalg.inv(F.T @ F + lam * np.eye(n_dims)) @ F.T @ Y
    else:
        W = F.T @ np.linalg.inv(F @ F.T + lam * np.eye(n_samples)) @ Y
    W = W.T  # (n_classes, n_dims)

    def predict(fp_new):
        scores = W @ fp_new
        return class_ids[np.argmax(scores)]

    return predict, W


# ========== Experiments ==========
def run_experiment(class_ids, n_train, n_test, n_dims=256,
                   n_steps=3, noise_seed=42):
    print(f"\n{'─'*60}")
    print(f"  CNN → NCO Array (N={n_dims}, N_STEPS={n_steps})")
    print(f"  Classes: {class_ids}, Train: {n_train}/class, Test: {n_test}/class")
    print(f"{'─'*60}")

    # Load
    print("  Loading MNIST...")
    X_train, y_train = load_mnist(class_ids, n_train, 'training')
    X_test, y_test = load_mnist(class_ids, n_test, 'testing')
    print(f"  Train: {X_train.shape}, Test: {X_test.shape}")

    # Build CNN
    print("  Building CNN (Conv1→Pool→Conv2→Pool→FC128)...")
    cnn_forward = build_cnn()

    # Extract features
    print("  Extracting CNN features...")
    t0 = time.time()
    feat_train = cnn_forward(X_train)
    feat_test = cnn_forward(X_test)
    dt = time.time() - t0
    print(f"  Feature extraction: {dt:.2f}s ({X_train.shape[0]*2/dt:.0f} img/s)")

    # Create NCOs
    print(f"  Creating NCO array (N={n_dims})...")
    ncos = [NCO(THS[i % 6], OFFSETS[i % 6], seed=2000 + i * 10)
            for i in range(n_dims)]

    # Encode features
    print("  Encoding training features → NCO fingerprints...")
    t0 = time.time()
    fp_train = encode_nco_array(feat_train, ncos, n_steps, noise_seed)
    dt = time.time() - t0
    print(f"  Encoding time: {dt:.1f}s")

    # Train Linear Readout
    print("  Training Linear Readout (ridge reg)...")
    t0 = time.time()
    predict_fn, W = train_linear_readout(fp_train, y_train, class_ids, lam=0.1)
    dt = time.time() - t0
    print(f"  Training time: {dt:.2f}s")

    # Train accuracy
    correct = sum(1 for i in range(len(X_train))
                  if predict_fn(fp_train[i]) == y_train[i])
    train_acc = correct / len(X_train) * 100
    print(f"  Train accuracy: {train_acc:.2f}%")

    # Encode test
    print("  Encoding test features → NCO fingerprints...")
    fp_test = encode_nco_array(feat_test, ncos, n_steps, noise_seed + 1)

    # Test accuracy
    correct = sum(1 for i in range(len(X_test))
                  if predict_fn(fp_test[i]) == y_test[i])
    test_acc = correct / len(X_test) * 100
    print(f"  Test accuracy: {test_acc:.2f}%")

    # Per-class
    print("  Per-class:")
    for c in class_ids:
        mask = y_test == c
        if mask.sum() > 0:
            c_correct = sum(1 for i in np.where(mask)[0]
                          if predict_fn(fp_test[i]) == c)
            print(f"    Class {c}: {c_correct}/{mask.sum()}"
                  f" ({c_correct/mask.sum()*100:.1f}%)")

    return train_acc, test_acc


def main():
    print(SEP)
    print("  Onyx V4.1 — Hybrid CNN + NCO Array")
    print(SEP)
    print(f"  MNIST: {MNIST_PATH}")
    print(f"  Architecture: Conv2D(8)→Pool→Conv2D(16)→Pool→FC(128)→NCO(256)")
    print()

    results = []

    # ========== EXP 1: Binary (0 vs 1) ==========
    print(SEP)
    print("  EXP 1: Hybrid CNN+NCO — Binary (0 vs 1)")
    print(SEP)
    tr, te = run_experiment([0, 1], n_train=1000, n_test=500,
                           n_dims=256, n_steps=3)
    results.append(('binary', 256, 3, tr, te))

    # ========== EXP 2: 3-Class (0 vs 1 vs 6) ==========
    print(f"\n{SEP}")
    print("  EXP 2: Hybrid CNN+NCO — 3-Class (0 vs 1 vs 6)")
    print(SEP)
    for n_dims in [128, 256]:
        tr, te = run_experiment([0, 1, 6], n_train=600, n_test=300,
                               n_dims=n_dims, n_steps=3)
        results.append(('3class', n_dims, 3, tr, te))

    # ========== EXP 3: 10-Class MNIST ==========
    print(f"\n{SEP}")
    print("  EXP 3: Hybrid CNN+NCO — 10-Class MNIST")
    print(SEP)
    for n_dims in [128, 256, 512]:
        tr, te = run_experiment(list(range(10)),
                               n_train=500, n_test=500,
                               n_dims=n_dims, n_steps=3)
        results.append(('10class', n_dims, 3, tr, te))

    # ========== SUMMARY ==========
    print(f"\n\n{SEP}")
    print("  HYBRID CNN+NCO — RESULTS SUMMARY")
    print(SEP)
    header = f"  {'Experiment':<18} {'N_DIMS':>6} {'N_STEPS':>8} {'Train':>8} {'Test':>8}"
    print(header)
    print('  ' + '-' * 52)
    for exp, nd, ns, tr, te in results:
        print(f"  {exp:<18} {nd:>6} {ns:>8} {tr:>7.1f}% {te:>7.1f}%")

    print(f"\n{SEP}")
    print("  Experiment Complete.")
    print(SEP)


if __name__ == "__main__":
    main()
