#!/usr/bin/env python3
"""
Onyx v2 — Enhanced: Gaussian noise + N_WINDOW sweep + MNIST (PNG loader)
=================================================================================
PART 1: Binary (± signals) + Multi-level amplitude
PART 2: MNIST with NCO Tank per Class (firing-rate voting)
PART 3: MNIST with NCO Array + Random Projection (HD encoding)

MNIST loader uses PNG files (pure Python, no numpy/PIL needed).
"""

import random
import math
import time
import os
import sys

# ========== المعاملات الأساسية ==========
N_SAMPLES_TEST = 200          # عينات MNIST لكل فئة
N_SAMPLES = 50                # عينات binary (±)
N_OSC = 6
TH = 2**30
OFFSET = TH // 2
F_WORD = 2**28
THS = [int(TH * (0.8 + 0.4 * i / N_OSC)) for i in range(N_OSC)]
OFFSETS = [ths // 2 for ths in THS]
NOISE_STD = TH // 4           # σ = TH/4 ~ 2^28


# ========== NCO ==========
class NCO:
    __slots__ = ('acc', 'th', 'offset', 'firing_dir', 'n_fires', 'seed', '_rng')
    def __init__(self, th, offset, seed):
        self.acc = 0
        self.th = th
        self.offset = offset
        self.firing_dir = 0
        self.n_fires = 0
        self.seed = seed
        self._rng = random.Random(seed)

    def reset(self):
        self.acc = 0
        self.firing_dir = 0
        self.n_fires = 0

    def step_gaussian(self, drive):
        fw = int(F_WORD + drive)
        noise = int(self._rng.gauss(0, NOISE_STD))
        self.acc += fw + noise
        if self.acc > self.th:
            self.firing_dir = 1
            self.n_fires += 1
            self.acc -= self.offset
        elif self.acc < -self.th:
            self.firing_dir = -1
            self.n_fires += 1
            self.acc += self.offset

    def step_uniform(self, drive):
        fw = int(F_WORD + drive)
        noise = int(self._rng.uniform(-NOISE_STD * 2, NOISE_STD * 2))
        self.acc += fw + noise
        if self.acc > self.th:
            self.firing_dir = 1
            self.n_fires += 1
            self.acc -= self.offset
        elif self.acc < -self.th:
            self.firing_dir = -1
            self.n_fires += 1
            self.acc += self.offset


def fde_vote(oscs):
    pos = sum(1 for o in oscs if o.firing_dir > 0)
    neg = sum(1 for o in oscs if o.firing_dir < 0)
    if pos > neg:
        return 1
    elif neg > pos:
        return -1
    total_pos = sum(o.n_fires for o in oscs if o.firing_dir > 0)
    total_neg = sum(o.n_fires for o in oscs if o.firing_dir < 0)
    return 1 if total_pos >= total_neg else -1


# ========== PNG Loader (pure Python — minimal PNG parser) ==========
def load_png_grayscale(path):
    """
    Load a PNG file and return flat list of pixel values (0-255).
    Pure Python — handles basic grayscale PNGs (MNIST format).
    """
    with open(path, 'rb') as f:
        raw = f.read()

    # Only care about IDAT chunks — extract pixel data
    # We know MNIST PNGs are 28x28, grayscale, no interlacing
    idx = raw.find(b'IDAT')
    if idx < 0:
        return None

    # Extract all IDAT chunks (there could be multiple)
    idat_data = b''
    pos = idx - 4  # back up to chunk length
    while True:
        # Find next IDAT
        idat_start = raw.find(b'IDAT', pos + 4)
        chunk_start = idat_start - 4 if idat_start >= 0 else None

        # Read current chunk length
        if chunk_start is None or chunk_start >= len(raw) - 4:
            # No more IDATs — use what we have
            # Read the first IDAT chunk
            clen = int.from_bytes(raw[pos:pos+4], 'big')
            idat_data = raw[pos+8:pos+8+clen]
            break
        else:
            clen = int.from_bytes(raw[chunk_start:chunk_start+4], 'big')
            idat_data = raw[chunk_start+8:chunk_start+8+clen]
            pos = chunk_start
            break  # Just use first IDAT for simplicity

    if not idat_data:
        return None

    import zlib
    try:
        decompressed = zlib.decompress(idat_data)
    except:
        return None

    # PNG: each row starts with filter byte
    # For 28x28 grayscale: 28 bytes per row + 1 filter byte
    pixels = []
    row_size = 29  # 28 pixels + 1 filter byte
    rows_expected = 28

    for row_idx in range(rows_expected):
        start = row_idx * row_size + 1  # skip filter byte
        row_pixels = decompressed[start:start + 28]
        # Apply filter: Sub filter (1), Up filter (2), Average(3), Paeth(4)
        # For simplicity, just take raw values — MNIST has low filter complexity
        pixels.extend(row_pixels)

    return list(pixels) if len(pixels) == 784 else None


def load_mnist_png(base_path, class_ids, n_per_class, split='testing'):
    """Load MNIST PNG samples by class. Returns (images, labels)."""
    images = []
    labels = []
    for cls in class_ids:
        cls_dir = os.path.join(base_path, split, str(cls))
        if not os.path.exists(cls_dir):
            print(f"  WARNING: {cls_dir} not found!", file=sys.stderr)
            continue
        files = sorted(os.listdir(cls_dir))[:n_per_class]
        for fname in files:
            fpath = os.path.join(cls_dir, fname)
            pixels = load_png_grayscale(fpath)
            if pixels and len(pixels) == 784:
                images.append(pixels)
                labels.append(cls)
            if len(labels) >= n_per_class:
                break
    return images, labels


# ========== Phase 1: Binary (± signals) ==========
def run_binary(n_steps, noise_type):
    random.seed(42)
    signals, expected = [], []
    for i in range(N_SAMPLES):
        if i < N_SAMPLES // 2:
            sig = 0.5 + random.gauss(0, 0.1)
            exp = 1
        else:
            sig = -0.5 + random.gauss(0, 0.1)
            exp = -1
        signals.append(sig)
        expected.append(exp)

    oscs = [NCO(THS[i], OFFSETS[i], seed=42 + i*100) for i in range(N_OSC)]
    correct = 0
    total_fires = 0

    for i in range(len(signals)):
        for o in oscs:
            o.reset()
        drive = int(signals[i] * TH * 2)
        for _ in range(n_steps):
            for o in oscs:
                if noise_type == 'gaussian':
                    o.step_gaussian(drive)
                else:
                    o.step_uniform(drive)
        decision = fde_vote(oscs)
        for o in oscs:
            total_fires += o.n_fires
        if decision == expected[i]:
            correct += 1

    return correct / len(signals) * 100, total_fires


# ========== Phase 2: Multi-Level Amplitude ==========
def run_multi_level(n_steps, noise_type, n_levels=5):
    signals, expected = [], []
    for level in range(n_levels):
        amp = 0.2 + 0.2 * level
        for _ in range(10):
            sig = amp + random.gauss(0, 0.05)
            signals.append(sig)
            expected.append(level)

    oscs = [NCO(THS[i], OFFSETS[i], seed=42 + i*100) for i in range(N_OSC)]
    correct = 0

    for i in range(len(signals)):
        for o in oscs:
            o.reset()
        drive = int(signals[i] * TH * 2)
        for _ in range(n_steps):
            for o in oscs:
                if noise_type == 'gaussian':
                    o.step_gaussian(drive)
                else:
                    o.step_uniform(drive)
        avg_fires = sum(o.n_fires for o in oscs) / N_OSC
        predicted = min(n_levels - 1, int(avg_fires / 3))
        if predicted == expected[i]:
            correct += 1

    return correct / len(signals) * 100, sum(o.n_fires for o in oscs)


# ========== Phase 3+4: MNIST NCO Tank per Class ==========
def mnist_nco_classify(images, labels, n_steps, noise_type, class_ids):
    """NCO Tank per Class. Decision: class with highest total firing."""
    label_map = {c: i for i, c in enumerate(class_ids)}
    n_classes = len(class_ids)
    n_samples = len(images)
    correct = 0
    total_fires = 0

    tanks = []
    for c in range(n_classes):
        tank = [NCO(THS[i], OFFSETS[i], seed=1000 + c*100 + i*10) for i in range(N_OSC)]
        tanks.append(tank)

    for s in range(n_samples):
        img = images[s]
        true_label = label_map[labels[s]]
        mn = sum(img) / len(img)

        # base_drive = average pixel (0-255) → scaled to ±TH
        base_drive = int((mn / 127.5 - 1.0) * TH * 0.5)

        class_fires = [0] * n_classes

        for c in range(n_classes):
            tank = tanks[c]
            for o in tank:
                o.reset()
            gain = 0.8 + 0.4 * c / max(1, n_classes - 1)
            drive = int(base_drive * gain)

            for _ in range(n_steps):
                for o in tank:
                    if noise_type == 'gaussian':
                        o.step_gaussian(drive)
                    else:
                        o.step_uniform(drive)

            class_fires[c] = sum(o.n_fires for o in tank)
            total_fires += class_fires[c]

        predicted = class_fires.index(max(class_fires))
        if predicted == true_label:
            correct += 1

    acc = correct / n_samples * 100
    avg_f = total_fires / n_samples
    return acc, avg_f


# ========== HD Encoder (Random Projection + NCO Array) ==========
def hd_nco_classify(images, labels, n_steps, noise_type, class_ids,
                     n_hyper=256, alpha=5.0):
    """
    HD NCO Array: كل صورة → Random Projection → NCO per dimension → fingerprint
    التصنيف عبر أقرب مسافة Hamming إلى class templates.
    """
    import struct, hashlib
    label_map = {c: i for i, c in enumerate(class_ids)}
    n_classes = len(class_ids)
    n_samples = len(images)
    n_pixels = len(images[0])

    # Random projection matrix (seeded for reproducibility)
    rng = random.Random(42)
    proj = [[rng.gauss(0, 0.1) for _ in range(n_pixels)] for _ in range(n_hyper)]

    # NCOs per dimension
    ncos = [NCO(THS[i % N_OSC], OFFSETS[i % N_OSC], seed=2000 + i*10) for i in range(n_hyper)]

    step_fn = 'gaussian' if noise_type == 'gaussian' else 'uniform'

    def encode_to_fp(img_pixels):
        """Encode single image → fingerprint vector (list of ±1)."""
        # Normalize pixels to [0,1] then center
        mean_px = sum(img_pixels) / len(img_pixels)
        std_px = math.sqrt(sum((p - mean_px)**2 for p in img_pixels) / len(img_pixels)) or 1.0
        centered = [(p - mean_px) / std_px for p in img_pixels]

        fp = [0] * n_hyper
        for d in range(n_hyper):
            # Dot product with projection row
            proj_val = sum(centered[p] * proj[d][p] for p in range(n_pixels))
            proj_val = proj_val * alpha / 3.0  # scale to reasonable range

            o = ncos[d]
            o.reset()
            drive = int(proj_val * TH * 0.3)  # scaled drive

            for _ in range(n_steps):
                if step_fn == 'gaussian':
                    o.step_gaussian(drive)
                else:
                    o.step_uniform(drive)

            fp[d] = o.firing_dir  # +1, -1, or 0
        return fp

    # Encode all images
    fingerprints = [encode_to_fp(images[i]) for i in range(n_samples)]

    # Build class templates (average fingerprint per class)
    templates = {}
    for c in class_ids:
        members = [fp for fp, lbl in zip(fingerprints, labels) if lbl == c]
        if members:
            avg = [sum(members[j][d] for j in range(len(members))) for d in range(n_hyper)]
            templates[c] = [1 if v >= 0 else -1 for v in avg]
        else:
            templates[c] = [1] * n_hyper

    # Classify by Hamming distance
    correct = 0
    for i in range(n_samples):
        fp = fingerprints[i]
        true = label_map[labels[i]]
        best_dist = float('inf')
        pred = -1
        for c in class_ids:
            tpl = templates[c]
            dist = sum(1 for d in range(n_hyper) if fp[d] != tpl[d])
            if dist < best_dist:
                best_dist = dist
                pred = label_map[c]
        if pred == true:
            correct += 1

    return correct / n_samples * 100, fingerprints


# ========== Main ==========
def main():
    sep = '=' * 72
    print(sep)
    print("  Onyx v2 — Enhanced: Gaussian Noise + N_WINDOW Sweep")
    print(sep)
    print(f"  N_OSC = {N_OSC},  TH = 2^{int(math.log2(TH))},  F_WORD = 2^{int(math.log2(F_WORD))}")
    print(f"  Noise STD (Gaussian) = {NOISE_STD}")
    print(f"  Noise range (Uniform) = ±{NOISE_STD * 2}")
    print()

    # MNIST path
    mnist_base = "/workspaces/onyx-v2/mnist_png"
    mnist_ok = os.path.exists(mnist_base)

    if mnist_ok:
        print(f"  MNIST PNG found at {mnist_base}")
    else:
        print("  MNIST NOT found — synthetic signals only")
    print()

    # ==========================================
    # PHASE 1: Binary (± signals)
    # ==========================================
    print(sep)
    print("  PHASE 1: Binary Classification (±0.5 signals, 50 samples)")
    print(sep)

    for noise_type in ['gaussian', 'uniform']:
        print(f"\n  --- Noise: {noise_type.upper()} ---")
        print(f"  {'N_STEPS':>8} | {'Accuracy':>9} | {'Firings':>8} | {'Time(ms)':>9}")
        print('  ' + '-' * 45)
        for ns in [200, 100, 50, 20, 10, 5, 3, 2]:
            t0 = time.time()
            acc, nf = run_binary(ns, noise_type)
            dt = (time.time() - t0) * 1000
            print(f"  {ns:>8} | {acc:>8.1f}% | {nf:>8} | {dt:>8.2f}")

    # ==========================================
    # PHASE 2: Multi-Level
    # ==========================================
    print(f"\n{sep}")
    print("  PHASE 2: Multi-Level Amplitude (5 levels, 50 samples)")
    print(sep)
    for noise_type in ['gaussian', 'uniform']:
        print(f"\n  --- Noise: {noise_type.upper()} ---")
        print(f"  {'N_STEPS':>8} | {'Accuracy':>9} | {'Firings':>8}")
        print('  ' + '-' * 35)
        for ns in [20, 10, 5, 3, 2]:
            t0 = time.time()
            acc, nf = run_multi_level(ns, noise_type)
            dt = (time.time() - t0) * 1000
            print(f"  {ns:>8} | {acc:>8.1f}% | {nf:>8}")

    # ==========================================
    # PHASE 3-4: MNIST
    # ==========================================
    if mnist_ok:
        print(f"\n{sep}")
        print("  PHASE 3: MNIST — NCO Tank per Class (Firing-Rate)")
        print(sep)

        # 3A: Binary (0 vs 1)
        print("\n  --- 3A: Binary MNIST (0 vs 1) ---")
        imgs_01, lbls_01 = load_mnist_png(mnist_base, [0, 1], N_SAMPLES_TEST, 'testing')
        print(f"  Loaded {len(imgs_01)} samples ({len([l for l in lbls_01 if l==0])} x 0, "
              f"{len([l for l in lbls_01 if l==1])} x 1)")

        for noise_type in ['gaussian', 'uniform']:
            print(f"  Noise: {noise_type.upper():>8}")
            print(f"  {'N_STEPS':>8} | {'Accuracy':>9} | {'AvgFires':>9} | {'Time(ms)':>9}")
            print('  ' + '-' * 45)
            for ns in [10, 5, 3, 2]:
                t0 = time.time()
                acc, avg_f = mnist_nco_classify(imgs_01, lbls_01, ns, noise_type, [0, 1])
                dt = (time.time() - t0) * 1000
                print(f"  {ns:>8} | {acc:>8.2f}% | {avg_f:>8.1f} | {dt:>8.2f}")

        # 3B: 3-Class (0 vs 1 vs 6)
        print("\n  --- 3B: 3-Class MNIST (0 vs 1 vs 6) ---")
        imgs_016, lbls_016 = load_mnist_png(mnist_base, [0, 1, 6], N_SAMPLES_TEST, 'testing')
        print(f"  Loaded {len(imgs_016)} samples")

        for noise_type in ['gaussian', 'uniform']:
            print(f"  Noise: {noise_type.upper():>8}")
            print(f"  {'N_STEPS':>8} | {'Accuracy':>9} | {'AvgFires':>9} | {'Time(ms)':>9}")
            print('  ' + '-' * 45)
            for ns in [10, 5, 3, 2]:
                t0 = time.time()
                acc, avg_f = mnist_nco_classify(imgs_016, lbls_016, ns, noise_type, [0, 1, 6])
                dt = (time.time() - t0) * 1000
                print(f"  {ns:>8} | {acc:>8.2f}% | {avg_f:>8.1f} | {dt:>8.2f}")

        # PHASE 4: HD NCO Array (optional — computational cost is high in pure Python)
        print(f"\n{sep}")
        print("  PHASE 4: MNIST — HD NCO Array (256 dims, Hamming Distance)")
        print(sep)
        n_hyper = 256  # small for pure Python
        print(f"\n  Random Projection → {n_hyper} NCOs → FPGA-compatible")

        # 4A: Binary only (3-class is too slow in pure Python)
        print("\n  --- 4A: Binary MNIST (0 vs 1) ---")
        for noise_type in ['gaussian', 'uniform']:
            print(f"  Noise: {noise_type.upper():>8}")
            print(f"  {'N_STEPS':>8} | {'Accuracy':>9} | {'Time(s)':>9}")
            print('  ' + '-' * 35)
            for ns in [5, 3, 2]:
                t0 = time.time()
                acc, fps = hd_nco_classify(imgs_01, lbls_01, ns, noise_type,
                                          [0, 1], n_hyper=n_hyper)
                dt = time.time() - t0
                print(f"  {ns:>8} | {acc:>8.2f}% | {dt:>8.3f}")

    print(f"\n{sep}")
    print("  Experiment Complete.")
    print(sep)


if __name__ == "__main__":
    main()
