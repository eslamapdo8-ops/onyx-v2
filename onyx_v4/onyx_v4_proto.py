#!/usr/bin/env python3
"""
Onyx V4 — HD NCO Array: Prototype v0.1
========================================
HD NCO Array + Random Projection + Hamming Distance / Linear Readout
التصنيف متعدد الفئات على MNIST الحقيقي.

الاستراتيجية:
  1. Random Projection (Gaussian, كثافة 10% أو كاملة)
  2. كل بُعد ← NCO واحد ← بصمة ±1
  3. التصنيف: إما Hamming Distance أو Linear Readout (LMS)

اختبارات:
  - MNIST ثنائي (0 vs 1)
  - MNIST 3 فئات (0 vs 1 vs 6)
  - MNIST كامل (10 فئات) — مع Linear Readout
"""

import os, sys, math, time, random
import numpy as np
from PIL import Image

SEP = '=' * 72
MNIST_PATH = "/workspaces/onyx-v2/mnist_png"

# NCO parameters (same as V2 but scaled down for simulation)
TH = 2**30
OFFSET = TH // 2
F_WORD = 2**28
THS = np.array([int(TH * (0.8 + 0.4 * i / 6)) for i in range(6)])
OFFSETS = THS // 2


class NCO:
    """NCO oscillator — 32-bit signed accumulator, uniform noise."""
    __slots__ = ('acc', 'th', 'offset', 'firing_dir', 'fire_count', 'seed')
    def __init__(self, th, offset, seed):
        self.acc = 0
        self.th = th
        self.offset = offset
        self.firing_dir = 0
        self.fire_count = 0
        self.seed = seed
        np.random.seed(seed)  # per-NCO random source

    def reset(self):
        self.acc = 0
        self.firing_dir = 0
        self.fire_count = 0

    def step(self, drive, n_steps=3):
        """Run NCO for n_steps clock cycles. Uniform noise matching Verilog LFSR."""
        for _ in range(n_steps):
            # Uniform noise ±TH/8 (matching Verilog: permuted LFSR / 16)
            noise = int(np.random.randint(-TH // 8, TH // 8))
            self.acc += int(drive) + noise
            if self.acc > self.th:
                self.firing_dir = 1
                self.fire_count += 1
                self.acc -= self.offset
            elif self.acc < -self.th:
                self.firing_dir = -1
                self.fire_count += 1
                self.acc += self.offset


def load_mnist_png_arrays(class_ids, n_per, split='testing'):
    """Load MNIST PNGs into numpy arrays. Returns (images_np, labels_np)."""
    images, labels = [], []
    for cls in class_ids:
        cls_dir = os.path.join(MNIST_PATH, split, str(cls))
        if not os.path.exists(cls_dir):
            continue
        files = sorted(os.listdir(cls_dir))[:n_per]
        for fname in files:
            img = Image.open(os.path.join(cls_dir, fname)).convert('L')
            arr = np.array(img, dtype=np.uint8).flatten()
            images.append(arr)
            labels.append(cls)
    return np.array(images), np.array(labels)


def encode_nco_array(images, proj_matrix, ncos, n_steps=3):
    """
    Encode images to fingerprints using NCO array.
    proj_matrix: (N_DIMS x N_PIXELS) — random projection
    ncos: list of NCO objects, one per dim
    Returns: fingerprints (N x N_DIMS) of ±1 values
    """
    n_samples = images.shape[0]
    n_dims = proj_matrix.shape[0]
    fingerprints = np.zeros((n_samples, n_dims), dtype=np.int8)

    for s in range(n_samples):
        if s % 200 == 0 and s > 0:
            print(f"    encoded {s}/{n_samples}", file=sys.stderr)

        # Image → centered + normalized
        img = images[s].astype(np.float32)
        mn = img.mean()
        std = img.std()
        if std < 1e-6:
            centered = np.zeros_like(img)
        else:
            centered = (img - mn) / std

        # Random projection
        proj = proj_matrix @ centered  # (N_DIMS,)

        # Scale to reasonable drive range (±TH)
        scale = TH * 0.15 / max(np.abs(proj).max(), 1.0)

        for d in range(n_dims):
            ncos[d].reset()
            drive = int(proj[d] * scale)
            ncos[d].step(drive, n_steps)
            fingerprints[s, d] = ncos[d].firing_dir

    return fingerprints


def train_templates(fingerprints, labels, class_ids):
    """Build class templates: average fingerprint per class."""
    templates = {}
    for c in class_ids:
        mask = labels == c
        if mask.sum() > 0:
            avg = fingerprints[mask].mean(axis=0)
            templates[c] = np.sign(avg)
        else:
            templates[c] = np.ones(fingerprints.shape[1], dtype=np.int8)
    return templates


def train_linear_readout(fingerprints, labels, class_ids):
    """
    Train Linear Readout via pseudo-inverse.
    W_out = Y @ F^+ where F is fingerprint matrix, Y is one-hot labels.
    """
    n_classes = len(class_ids)
    n_dims = fingerprints.shape[1]
    n_samples = fingerprints.shape[0]

    # One-hot targets
    label_to_idx = {c: i for i, c in enumerate(class_ids)}
    Y = np.zeros((n_samples, n_classes))
    for i, lbl in enumerate(labels):
        Y[i, label_to_idx[lbl]] = 1.0

    # Ridge regression: W = (F^T F + λI)^{-1} F^T Y
    # Works when n_dims > n_samples or n_dims < n_samples
    lam = 1.0  # strong regularization for small sample size
    F = fingerprints.astype(np.float64)
    n_dims = F.shape[1]
    W = np.linalg.inv(F.T @ F + lam * np.eye(n_dims)) @ F.T @ Y
    W = W.T  # now W: (n_classes, n_dims)

    def predict(fp_new):
        """fp_new: (N_DIMS,) fingerprint vector."""
        scores = W @ fp_new
        return class_ids[np.argmax(scores)]

    return predict


def hamming_classify(fp, templates):
    """Classify single fingerprint via Hamming distance to templates."""
    best_dist = float('inf')
    best_class = -1
    for c, tpl in templates.items():
        dist = np.sum(fp != tpl)
        if dist < best_dist:
            best_dist = dist
            best_class = c
    return best_class


def run_experiment(class_ids, n_train=200, n_test=200, n_dims=256,
                   n_steps=3, sparsity=0.1,
                   classifier='hamming', alpha=5.0):
    """
    Full MNIST experiment with NCO Array.
    Returns: train_accuracy, test_accuracy
    """
    print(f"\n{'─'*60}")
    print(f"  Config: N_DIMS={n_dims}, N_STEPS={n_steps}, "
          f"sparsity={sparsity}, classifier={classifier}")
    print(f"  Classes: {class_ids}")
    print(f"  Train: {n_train}/class, Test: {n_test}/class")
    print(f"{'─'*60}")

    # Load data
    print("  Loading MNIST...")
    X_train, y_train = load_mnist_png_arrays(class_ids, n_train, 'training')
    X_test, y_test = load_mnist_png_arrays(class_ids, n_test, 'testing')
    n_pixels = X_train.shape[1]
    print(f"  Train: {X_train.shape}, Test: {X_test.shape}")

    # Random projection matrix
    print("  Building Random Projection...")
    if sparsity < 1.0:
        proj = np.random.randn(n_dims, n_pixels) * np.sqrt(1 / (sparsity * n_pixels))
        mask = np.random.random((n_dims, n_pixels)) < sparsity
        proj = proj * mask
    else:
        proj = np.random.randn(n_dims, n_pixels) / np.sqrt(n_pixels)

    # Create NCOs
    print("  Creating NCO array...")
    ncos = [NCO(THS[i % 6], OFFSETS[i % 6], seed=2000 + i * 10)
            for i in range(n_dims)]

    # Encode training set
    print("  Encoding training set...")
    t0 = time.time()
    fp_train = encode_nco_array(X_train, proj, ncos, n_steps)
    dt = time.time() - t0
    print(f"  Encoding time: {dt:.1f}s ({X_train.shape[0] * n_dims * n_steps / dt:.0f} ops/s)")

    # Train classifier
    if classifier == 'hamming':
        print("  Building templates (Hamming)...")
        templates = train_templates(fp_train, y_train, class_ids)
        def classify(fp):
            return hamming_classify(fp, templates)
    elif classifier == 'linear':
        print("  Training Linear Readout (ridge reg)...")
        t0 = time.time()
        classify_fn = train_linear_readout(fp_train, y_train, class_ids)
        dt = time.time() - t0
        print(f"  Training time: {dt:.2f}s")
        classify = classify_fn

    # Evaluate training
    correct = 0
    for i in range(len(X_train)):
        if classify(fp_train[i]) == y_train[i]:
            correct += 1
    train_acc = correct / len(X_train) * 100
    print(f"  Train accuracy: {train_acc:.2f}%")

    # Encode test set
    print("  Encoding test set...")
    fp_test = encode_nco_array(X_test, proj, ncos, n_steps)

    # Evaluate test
    correct = 0
    for i in range(len(X_test)):
        if classify(fp_test[i]) == y_test[i]:
            correct += 1
    test_acc = correct / len(X_test) * 100
    print(f"  Test accuracy: {test_acc:.2f}%")

    # Per-class accuracy
    print("  Per-class:")
    for c in class_ids:
        mask = y_test == c
        if mask.sum() > 0:
            c_correct = sum(1 for i in np.where(mask)[0]
                          if classify(fp_test[i]) == c)
            print(f"    Class {c}: {c_correct}/{mask.sum()} "
                  f"({c_correct/mask.sum()*100:.1f}%)")

    return train_acc, test_acc


def main():
    print(SEP)
    print("  Onyx V4 — HD NCO Array Prototype v0.1")
    print(SEP)
    print(f"  MNIST: {MNIST_PATH}")
    print(f"  NCO: TH=2^30, Offset=TH/2, F_Word=2^28")
    print()

    results = []

    # ==========================================
    # Experiment 1: Hamming, Binary (0 vs 1)
    # ==========================================
    print(SEP)
    print("  EXP 1: Hamming — Binary (0 vs 1)")
    print(SEP)
    for n_dims in [256]:  # N=256 proved 100% in earlier test
        for n_steps in [3]:
            tr, te = run_experiment([0, 1], n_train=200, n_test=200,
                                   n_dims=n_dims, n_steps=n_steps,
                                   classifier='hamming')
            results.append(('binary', n_dims, n_steps, 'hamming', tr, te))

    # ==========================================
    # Experiment 2: Hamming + Linear, 3-Class
    # ==========================================
    print(f"\n{SEP}")
    print("  EXP 2: 3-Class (0 vs 1 vs 6) — Hamming vs Linear")
    print(SEP)
    for method in ['hamming', 'linear']:
        for n_dims in [256, 512]:
            tr, te = run_experiment([0, 1, 6], n_train=300, n_test=200,
                                   n_dims=n_dims, n_steps=3,
                                   classifier=method)
            results.append(('3class', n_dims, 3, method, tr, te))

    # ==========================================
    # Experiment 3: Linear Readout, 10-Class
    # ==========================================
    print(f"\n{SEP}")
    print("  EXP 3: Linear Readout — 10-Class MNIST")
    print(SEP)
    for n_dims in [256, 512]:
        tr, te = run_experiment(list(range(10)),
                               n_train=200, n_test=200,
                               n_dims=n_dims, n_steps=3,
                               classifier='linear')
        results.append(('10class', n_dims, 3, 'linear', tr, te))

    # ==========================================
    # Experiment 4: Linear Readout, Binary — full data
    # ==========================================
    print(f"\n{SEP}")
    print("  EXP 4: Linear Readout — Binary (full data)")
    print(SEP)
    tr, te = run_experiment([0, 1], n_train=1000, n_test=500,
                           n_dims=256, n_steps=3,
                           classifier='linear')
    results.append(('binary_full', 256, 3, 'linear', tr, te))

    # ==========================================
    # Summary
    # ==========================================
    print(f"\n\n{'='*72}")
    print("  RESULTS SUMMARY")
    print('='*72)
    header = f"  {'Experiment':<18} {'N_DIMS':>6} {'N_STEPS':>8} {'Method':<12} {'Train':>8} {'Test':>8}"
    print(header)
    print('  ' + '-' * 64)
    for exp, nd, ns, method, tr, te in results:
        label = f"{exp}"
        print(f"  {label:<18} {nd:>6} {ns:>8} {method:<12} {tr:>7.1f}% {te:>7.1f}%")

    print(SEP)
    print("  Experiment Complete.")
    print(SEP)


if __name__ == "__main__":
    main()
