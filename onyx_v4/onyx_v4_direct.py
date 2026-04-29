#!/usr/bin/env python3
"""
Onyx V4.2 — Direct NCO Array + Linear Readout (no CNN)
=========================================================
بعد فشل CNN العشوائي، نعتمد على NCO Array المباشر:
  - Random Projection (Gaussian, كثافة 50%)
  - NCO Array (N=256, 512, 1024)
  - Linear Readout (Ridge Regression)
  - MNIST 10 فئات (train=500/class, test=500/class)

اختبار وحيد سريع بدلاً من سلسلة تجارب.
"""

import os, sys, math, time
import numpy as np
from PIL import Image

MNIST_PATH = "/workspaces/onyx-v2/mnist_png"
SEP = '=' * 72

TH = 2**30; OFFSET = TH // 2
THS = np.array([int(TH * (0.8 + 0.4 * i / 6)) for i in range(6)])
OFFSETS = THS // 2

class NCO:
    __slots__ = ('acc', 'th', 'offset', 'firing_dir', 'fire_count', 'seed')
    def __init__(self, th, offset, seed):
        self.acc = 0; self.th = th; self.offset = offset
        self.firing_dir = 0; self.fire_count = 0; self.seed = seed
    def reset(self):
        self.acc = 0; self.firing_dir = 0; self.fire_count = 0
    def step(self, drive, n_steps=3):
        rng = np.random.RandomState(self.seed)
        for _ in range(n_steps):
            noise = int(rng.randint(-TH // 8, TH // 8))
            self.acc += int(drive) + noise
            if self.acc > self.th:
                self.firing_dir = 1; self.fire_count += 1; self.acc -= self.offset
            elif self.acc < -self.th:
                self.firing_dir = -1; self.fire_count += 1; self.acc += self.offset

def load_mnist_flat(class_ids, n_per, split='testing'):
    images, labels = [], []
    for cls in class_ids:
        d = os.path.join(MNIST_PATH, split, str(cls))
        for f in sorted(os.listdir(d))[:n_per]:
            arr = np.array(Image.open(os.path.join(d, f)).convert('L'), dtype=np.uint8).flatten()
            images.append(arr); labels.append(cls)
    return np.array(images), np.array(labels)

def encode_fingerprints(images, proj, ncos, n_steps=3):
    N, D = len(images), len(ncos)
    fp = np.zeros((N, D), dtype=np.int8)
    for s in range(N):
        if s % 1000 == 0 and s > 0:
            print(f"  encoded {s}/{N}", file=sys.stderr)
        img = images[s].astype(np.float32)
        mn, std = img.mean(), img.std()
        centered = (img - mn) / std if std > 1e-6 else np.zeros_like(img)
        p = proj @ centered
        scale = TH * 0.4 / max(np.abs(p).max(), 1.0)
        for d in range(D):
            ncos[d].reset()
            ncos[d].step(int(p[d] * scale), n_steps)
            fp[s, d] = ncos[d].firing_dir
    return fp

def train_and_test(n_dims, n_steps, sparsity, n_train=500, n_test=500):
    print(SEP)
    print(f"  N={n_dims}, STEPS={n_steps}, SPARSITY={sparsity}")
    print(SEP)
    class_ids = list(range(10))
    print("  Loading MNIST...")
    Xtr, ytr = load_mnist_flat(class_ids, n_train, 'training')
    Xte, yte = load_mnist_flat(class_ids, n_test, 'testing')
    n_px = Xtr.shape[1]
    print(f"  Train: {Xtr.shape}, Test: {Xte.shape}")

    print("  Building Random Projection...")
    proj = np.random.randn(n_dims, n_px) / np.sqrt(n_px * sparsity)
    mask = np.random.random((n_dims, n_px)) < sparsity
    proj *= mask

    ncos = [NCO(THS[i%6], OFFSETS[i%6], seed=2000+i*10) for i in range(n_dims)]

    print("  Encoding training...")
    t0 = time.time()
    fp_tr = encode_fingerprints(Xtr, proj, ncos, n_steps)
    print(f"  Time: {time.time()-t0:.1f}s")

    print("  Training Linear Readout...")
    t0 = time.time()
    n_classes = 10; n_samp = fp_tr.shape[0]
    Y = np.zeros((n_samp, n_classes))
    for i, lbl in enumerate(ytr):
        Y[i, lbl] = 1.0
    F = fp_tr.astype(np.float64)
    lam = 1.0
    W = np.linalg.inv(F.T @ F + lam * np.eye(n_dims)) @ F.T @ Y
    W = W.T
    print(f"  Training time: {time.time()-t0:.2f}s")

    # Train acc
    pred_tr = np.argmax(W @ fp_tr.T, axis=0)
    tr_acc = np.mean(pred_tr == ytr) * 100
    print(f"  Train: {tr_acc:.2f}%")

    print("  Encoding test...")
    fp_te = encode_fingerprints(Xte, proj, ncos, n_steps)

    pred_te = np.argmax(W @ fp_te.T, axis=0)
    te_acc = np.mean(pred_te == yte) * 100
    print(f"  Test: {te_acc:.2f}%")

    print("  Per-class:")
    for c in range(10):
        mask = yte == c
        if mask.sum() > 0:
            ca = np.mean(pred_te[mask] == c) * 100
            print(f"    Class {c}: {ca:.1f}%")
    return tr_acc, te_acc

def main():
    print(SEP)
    print("  Onyx V4.2 — Direct NCO Array (best config)")
    print(SEP)
    print(f"  MNIST: {MNIST_PATH}")

    # Single best experiment: N=1024, STEPS=3, sparsity=0.5
    tr, te = train_and_test(n_dims=1024, n_steps=3, sparsity=0.5,
                           n_train=500, n_test=500)

    # Quick comparison: N=512
    tr2, te2 = train_and_test(n_dims=512, n_steps=3, sparsity=0.5,
                              n_train=500, n_test=500)

    print(f"\n{SEP}")
    print("  FINAL COMPARISON")
    print(SEP)
    print(f"  N=512:  Train={tr2:.1f}%  Test={te2:.1f}%")
    print(f"  N=1024: Train={tr:.1f}%  Test={te:.1f}%")
    print(f"\n  Recommendation: N={512 if te2 >= te else 1024} "
          f"for FPGA (≈{'42K' if te2 >= te else '83K'} LUTs)")

if __name__ == "__main__":
    main()
