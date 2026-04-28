#!/usr/bin/env python3
"""
Onyx v2 — Enhanced: Gaussian noise + N_WINDOW sweep + MNIST binary/multi-class
=================================================================================
No numpy — pure Python (Termux-compatible).
الكود يعمل على MNIST حقيقي + إشارات تركيبية.

المراحل:
  1. Binary (± signals) — التحقق من صحة الخوارزمية
  2. Multi-level Amplitude (5 levels)
  3. MNIST binary (0 vs 1) — NCO Tank per Class
  4. MNIST 3-class (0 vs 1 vs 6)
"""

import random
import math
import time
import struct
import gzip
import os
import sys

# ========== المعاملات الأساسية ==========
N_SAMPLES_TEST = 200          # عينات اختبار MNIST لكل فئة
N_SAMPLES = 50                # عينات binary (±)
N_OSC = 6
TH = 2**30
OFFSET = TH // 2
F_WORD = 2**28
THS = [int(TH * (0.8 + 0.4 * i / N_OSC)) for i in range(N_OSC)]
OFFSETS = [ths // 2 for ths in THS]
NOISE_STD = TH // 4

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
        step_fn = 'gaussian' if noise_type == 'gaussian' else 'uniform'
        for _ in range(n_steps):
            for o in oscs:
                if step_fn == 'gaussian':
                    o.step_gaussian(drive)
                else:
                    o.step_uniform(drive)
        decision = fde_vote(oscs)
        for o in oscs:
            total_fires += o.n_fires
        if decision == expected[i]:
            correct += 1

    return correct / len(signals) * 100, total_fires


# ========== Phase 2: Multi-Level ==========
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
        step_fn = 'gaussian' if noise_type == 'gaussian' else 'uniform'
        for _ in range(n_steps):
            for o in oscs:
                if step_fn == 'gaussian':
                    o.step_gaussian(drive)
                else:
                    o.step_uniform(drive)
        # استخدام avg fires للتمييز
        avg_fires = sum(o.n_fires for o in oscs) / N_OSC
        predicted = min(n_levels - 1, int(avg_fires / 3))
        if predicted == expected[i]:
            correct += 1

    return correct / len(signals) * 100, sum(o.n_fires for o in oscs)


# ========== MNIST Loader (pure Python) ==========
def load_mnist_images(path):
    if not os.path.exists(path):
        return None, None
    with gzip.open(path, 'rb') as f:
        magic, n, rows, cols = struct.unpack('>IIII', f.read(16))
        data_raw = f.read()
    images = []
    pixel_count = rows * cols
    offset = 0
    for _ in range(n):
        img = [b for b in data_raw[offset:offset + pixel_count]]
        images.append(img)
        offset += pixel_count
    return images, (rows, cols)

def load_mnist_labels(path):
    if not os.path.exists(path):
        return None
    with gzip.open(path, 'rb') as f:
        magic, n = struct.unpack('>II', f.read(8))
        return list(f.read(n))

def mean_img(img):
    return sum(img) / len(img)

def std_img(img, mean):
    var = sum((p - mean)**2 for p in img) / len(img)
    return math.sqrt(var) if var > 0 else 0.0


# ========== Phase 3-4: MNIST NCO Tank per Class ==========
def mnist_nco_classify(images_list, labels_list, n_steps, noise_type, class_ids=None):
    """
    NCO Tank per Class: كل فئة لها خزان NCOs.
    القرار: الفئة ذات أعلى إطلاق إجمالي.
    """
    if class_ids is None:
        class_ids = list(range(10))

    # تصفية
    filtered_images = []
    filtered_labels = []
    for img, lbl in zip(images_list, labels_list):
        if lbl in class_ids:
            filtered_images.append(img)
            filtered_labels.append(lbl)

    label_map = {orig: i for i, orig in enumerate(class_ids)}
    n_classes = len(class_ids)
    n_samples = len(filtered_images)
    correct = 0
    total_fires = 0

    # إنشاء خزانات — كل خزان = N_OSC مذبذبات
    tanks = []
    for c in range(n_classes):
        tank = [NCO(THS[i], OFFSETS[i], seed=1000 + c*100 + i*10) for i in range(N_OSC)]
        tanks.append(tank)

    step_fn = 'gaussian' if noise_type == 'gaussian' else 'uniform'

    for s in range(n_samples):
        img = filtered_images[s]
        true_label = label_map[filtered_labels[s]]
        mn = mean_img(img)

        # base_drive من متوسط الصورة
        base_drive = int((mn / 127.5 - 1.0) * TH * 0.5)

        class_fires = [0] * n_classes

        for c in range(n_classes):
            tank = tanks[c]
            for o in tank:
                o.reset()
            # gain مختلف لكل فئة
            gain = 0.8 + 0.4 * c / max(1, n_classes - 1)
            drive = int(base_drive * gain)

            for _ in range(n_steps):
                for o in tank:
                    if step_fn == 'gaussian':
                        o.step_gaussian(drive)
                    else:
                        o.step_uniform(drive)

            class_fires[c] = sum(o.n_fires for o in tank)
            total_fires += class_fires[c]

        predicted = class_fires.index(max(class_fires))
        if predicted == true_label:
            correct += 1

    accuracy = correct / n_samples * 100
    avg_fires = total_fires / n_samples
    return accuracy, avg_fires


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

    # تحميل MNIST
    base_path = os.path.expanduser("~/hd_nco_array")
    train_imgs, dims = load_mnist_images(os.path.join(base_path, "train-images-idx3-ubyte.gz"))
    train_lbls = load_mnist_labels(os.path.join(base_path, "train-labels-idx1-ubyte.gz"))
    test_imgs, _ = load_mnist_images(os.path.join(base_path, "t10k-images-idx3-ubyte.gz"))
    test_lbls = load_mnist_labels(os.path.join(base_path, "t10k-labels-idx1-ubyte.gz"))

    mnist_ok = (train_imgs is not None)
    if mnist_ok:
        print(f"  MNIST loaded: {len(train_imgs)} train, {len(test_imgs)} test")
    else:
        print("  MNIST NOT FOUND — using synthetic signals only")
    print()

    # ==========================================
    # PHASE 1: Binary
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
        print("  PHASE 3: MNIST — NCO Tank per Class (Firing-Rate Voting)")
        print(sep)

        # اختيار عينات
        def sample_by_class(images, labels, class_ids, n_per):
            result_imgs, result_lbls = [], []
            counts = {c: 0 for c in class_ids}
            for img, lbl in zip(images, labels):
                if lbl in class_ids and counts[lbl] < n_per:
                    result_imgs.append(img)
                    result_lbls.append(lbl)
                    counts[lbl] += 1
                if all(v >= n_per for v in counts.values()):
                    break
            return result_imgs, result_lbls

        # 3A: Binary (0 vs 1)
        print("\n  --- 3A: Binary MNIST (0 vs 1) ---")
        imgs_01, lbls_01 = sample_by_class(test_imgs, test_lbls, [0, 1], N_SAMPLES_TEST)

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
        imgs_016, lbls_016 = sample_by_class(test_imgs, test_lbls, [0, 1, 6], N_SAMPLES_TEST)

        for noise_type in ['gaussian', 'uniform']:
            print(f"  Noise: {noise_type.upper():>8}")
            print(f"  {'N_STEPS':>8} | {'Accuracy':>9} | {'AvgFires':>9} | {'Time(ms)':>9}")
            print('  ' + '-' * 45)
            for ns in [10, 5, 3, 2]:
                t0 = time.time()
                acc, avg_f = mnist_nco_classify(imgs_016, lbls_016, ns, noise_type, [0, 1, 6])
                dt = (time.time() - t0) * 1000
                print(f"  {ns:>8} | {acc:>8.2f}% | {avg_f:>8.1f} | {dt:>8.2f}")

    print(f"\n{sep}")
    print("  Experiment Complete.")
    print(sep)


if __name__ == "__main__":
    main()
