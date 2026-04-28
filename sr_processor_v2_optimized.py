#!/usr/bin/env python3
"""
Onyx v1 — EDP Optimization Sweep
=================================
تجربة N_STEPS = [200, 100, 50, 20] مع تسجيل:
- الدقة (Accuracy)
- الطاقة الكلية (pJ)
- الزمن الكلي (μs)
- EDP (pJ·μs)
- عدد الإطلاقات

يُحافظ على نفس البنية (LIF + FDE + 6 مذبذبات).
"""

import random

# ========== معاملات ثابتة ==========
N_SAMPLES   = 50
N_OSC       = 6
DT2         = 1e-6          # 1 μs
TAU         = 1e-6          # 1 μs  (dt/tau = 1)
C           = 1e-15         # 1 fF
R           = 100e3         # 100 kΩ
TH          = 0.15
DRIVE_GAIN  = 20.0
NOISE_FLOOR = 0.6

# عتبات مكسورة التماثل
THS = [TH * (0.8 + 0.4 * i / N_OSC) for i in range(N_OSC)]

# ========== الطاقة ==========
E_CHARGE = 0.5 * C * (0.4**2)   # 0.8 fJ
E_SWITCH = 0.5e-15              # 0.5 fJ


class LIF:
    __slots__ = ('v', 'th', 'firing_dir', 'n_fires', 'seed', '_rng')
    def __init__(self, th, seed):
        self.v = 0.0
        self.th = th
        self.firing_dir = 0
        self.n_fires = 0
        self.seed = seed
        self._rng = random.Random(seed)

    def step(self, drive):
        noise = self._rng.gauss(0, NOISE_FLOOR)
        dv = (-self.v + drive + noise) * (DT2 / TAU)
        self.v += dv
        if self.v > self.th:
            self.firing_dir = 1
            self.n_fires += 1
            self.v = -self.th / 2
        elif self.v < -self.th:
            self.firing_dir = -1
            self.n_fires += 1
            self.v = self.th / 2


def run_experiment(n_steps, samples, oscs, signals, expected):
    """
    تجربة واحدة مع n_steps خطوة زمنية.
    تعيد: (accuracy%, total_energy_pJ, total_time_us, edp, total_fires)
    """
    # إعادة ضبط المذبذبات
    correct = 0
    total_fires = 0

    for i in range(len(signals)):
        for o in oscs:
            o.v = 0.0
            o.firing_dir = 0
            o.n_fires = 0

        drive = signals[i] * DRIVE_GAIN

        for _ in range(n_steps):
            for o in oscs:
                o.step(drive)

        # FDE vote
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
    total_switches = total_fires
    energy = E_CHARGE * total_switches + E_SWITCH * total_switches
    energy_pJ = energy * 1e12
    total_time_us = n_steps * (DT2 * 1e6)           # μs
    edp = energy_pJ * total_time_us                  # pJ·μs

    return accuracy, energy_pJ, total_time_us, edp, total_fires


def main():
    N_STEPS_LIST = [200, 100, 50, 20, 10, 5]

    # توليد الإشارات (نفس الـ seed لكل التجارب)
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

    # ===== شريط العناوين =====
    sep = '=' * 70
    print(sep)
    print("Onyx v1 — EDP Optimization Sweep")
    print(sep)
    print(f"  Oscillators: {N_OSC}")
    print(f"  dt/tau: {DT2/TAU:.0f}")
    print(f"  Drive gain: {DRIVE_GAIN}, Noise floor: {NOISE_FLOOR}")
    print()

    # ===== رأس الجدول =====
    header = f"{'N_STEPS':>8} | {'Accuracy':>9} | {'Energy(pJ)':>10} | {'Time(us)':>9} | {'EDP(pJ·us)':>11} | {'Firings':>8}"
    bar = '-' * len(header)
    print(header)
    print(bar)

    results = []

    for ns in N_STEPS_LIST:
        # خزان جديد لكل تجربة (seeds متطابقة)
        oscs = [LIF(THS[i], seed=42 + i*100) for i in range(N_OSC)]
        acc, epj, tus, edp, nf = run_experiment(ns, N_SAMPLES, oscs, signals, expected)
        results.append((ns, acc, epj, tus, edp, nf))

        # صبغ أخضر للـ 100%, أصفر للأقل
        acc_str = f"{acc:.1f}%"
        row = f"{ns:>8} | {acc_str:>9} | {epj:>10.2f} | {tus:>9.1f} | {edp:>11.1f} | {nf:>8}"
        print(row)

    print(bar)

    # ===== التحليل =====
    print()
    print(sep)
    print("Analysis")
    print(sep)

    # أفضل EDP مع دقة 100%
    best = [r for r in results if r[1] == 100.0]
    if best:
        best_edp = min(best, key=lambda x: x[4])
        print(f"  Best EDP @ 100% accuracy: N_STEPS={best_edp[0]}, "
              f"EDP={best_edp[4]:.1f} pJ·us, Energy={best_edp[2]:.2f} pJ, "
              f"Time={best_edp[3]:.1f} us")

        # التحسن مقارنة بـ N_STEPS=200
        ref = results[0]  # 200 steps
        improvement = (ref[4] - best_edp[4]) / ref[4] * 100
        print(f"  Improvement vs N_STEPS=200: {improvement:.0f}%")
        print(f"  EDP reduction: {ref[4]:.1f} -> {best_edp[4]:.1f} pJ·us")

    # أدنى N_STEPS يحقق 100%
    min_steps = min((r for r in results if r[1] == 100.0), key=lambda x: x[0])
    print(f"  Minimum N_STEPS for 100%: {min_steps[0]} "
          f"(EDP={min_steps[4]:.1f} pJ·us)")

    print()
    print(sep)
    print("Experiment complete.")
    print(sep)


if __name__ == "__main__":
    main()
