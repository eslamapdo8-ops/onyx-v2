#!/usr/bin/env python3
"""
Onyx v2 — NCO Digital Oscillator (Python prototype)
====================================================
محاكاة v2 الرقمي (NCO + FDE) مع N_STEPS متغير (لاختبار 5, 10, 50, 200).

NCO = Numerically Controlled Oscillator
- signed 32-bit accumulator
- noise injection
- positive/negative threshold comparators
- FDE vote
"""

import random
import math

# ========== المعاملات ==========
N_SAMPLES = 50
N_OSC     = 6
TH        = 2**30           # عتبة الـ 32-bit
OFFSET    = TH // 2         # إعادة الضبط (تجنب الصفر)
F_WORD    = 2**28           # كلمة التردد (كمية الإضافة كل خطوة)

# عتبات مختلفة
THS = [int(TH * (0.8 + 0.4 * i / N_OSC)) for i in range(N_OSC)]
OFFSETS = [ths // 2 for ths in THS]


class NCO:
    """مذبذب رقمي (NCO) — signed 32-bit accumulator."""
    __slots__ = ('acc', 'th', 'offset', 'firing_dir', 'n_fires', 'seed', '_rng')
    def __init__(self, th, offset, seed):
        self.acc = 0
        self.th = th
        self.offset = offset
        self.firing_dir = 0
        self.n_fires = 0
        self.seed = seed
        self._rng = random.Random(seed)

    def step(self, drive):
        # drive يُضاف إلى كلمة التردد
        fw = int(F_WORD + drive)
        noise = int(self._rng.gauss(0, TH // 4))  # ضوضاء رقمية

        self.acc += fw + noise

        if self.acc > self.th:
            self.firing_dir = 1
            self.n_fires += 1
            self.acc -= self.offset
        elif self.acc < -self.th:
            self.firing_dir = -1
            self.n_fires += 1
            self.acc += self.offset


def run_experiment(n_steps, signals, expected):
    """نفس توقيع v1 — تُعيد (accuracy, n_fires)."""
    oscs = [NCO(THS[i], OFFSETS[i], seed=42 + i*100) for i in range(N_OSC)]
    correct = 0
    total_fires = 0

    for i in range(len(signals)):
        for o in oscs:
            o.acc = 0
            o.firing_dir = 0
            o.n_fires = 0

        # drive: إشارة رقمية من -TH إلى +TH
        drive = int(signals[i] * TH * 2)
        for _ in range(n_steps):
            for o in oscs:
                o.step(drive)

        # FDE
        pos = sum(1 for o in oscs if o.firing_dir > 0)
        neg = sum(1 for o in oscs if o.firing_dir < 0)
        if pos > neg:
            decision = 1
        elif neg > pos:
            decision = -1
        else:
            total_pos = sum(o.n_fires for o in oscs if o.firing_dir > 0)
            total_neg = sum(o.n_fires for o in oscs if o.firing_dir < 0)
            decision = 1 if total_pos >= total_neg else -1

        for o in oscs:
            total_fires += o.n_fires

        if decision == expected[i]:
            correct += 1

    accuracy = correct / len(signals) * 100
    return accuracy, total_fires


def main():
    N_STEPS_LIST = [200, 100, 50, 20, 10, 5, 3, 2]

    # توليد الإشارات (نفس v1)
    random.seed(42)
    signals = []
    expected = []
    for i in range(N_SAMPLES):
        if i < N_SAMPLES // 2:
            sig = 0.5 + random.gauss(0, 0.1)
            exp = 1
        else:
            sig = -0.5 + random.gauss(0, 0.1)
            exp = -1
        signals.append(sig)
        expected.append(exp)

    sep = '=' * 60
    print(sep)
    print("Onyx v2 — NCO Digital (Python Prototype)")
    print(sep)
    print(f"  Oscillators: {N_OSC}")
    print(f"  Threshold: 2^{int(math.log2(TH))} (signed 32-bit)")
    print(f"  F_Word: 2^{int(math.log2(F_WORD))}")
    print()

    header = f"{'N_STEPS':>8} | {'Accuracy':>9} | {'Firings':>8}"
    bar = '-' * len(header)
    print(header)
    print(bar)

    results = []

    for ns in N_STEPS_LIST:
        acc, nf = run_experiment(ns, signals, expected)
        results.append((ns, acc, nf))

        acc_str = f"{acc:.1f}%"
        print(f"{ns:>8} | {acc_str:>9} | {nf:>8}")

    print(bar)
    print()

    # تحليل
    print(sep)
    print("Analysis")
    print(sep)
    best = [r for r in results if r[1] == 100.0]
    if best:
        min_ns = min(best, key=lambda x: x[0])
        print(f"  Minimum N_STEPS for 100%: {min_ns[0]} (Firings: {min_ns[2]})")
    else:
        best_ac = max(results, key=lambda x: x[1])
        print(f"  Best accuracy achieved: {best_ac[1]:.1f}% at N_STEPS={best_ac[0]}")

    print()
    print(sep)
    print("Experiment complete.")
    print(sep)


if __name__ == "__main__":
    main()
