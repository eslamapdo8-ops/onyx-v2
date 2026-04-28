#!/usr/bin/env python3
"""
Onyx V3 — NCO Ensemble (Multi-class via parallel NCO banks)
=============================================================
لكل فئة: خزان NCO مستقل (6 مذبذبات) يعمل بـ FDE.
جميع الخزانات تعمل بالتوازي.
الفئة الفائزة = صاحبة أقوى صوت في اتجاه الإشارة (FDE).

3 فئات: 0.3 (ضعيف), 0.6 (متوسط), 1.0 (قوي)
"""

import random
import math

# ========== الفئات ==========
CLASSES = [
    {"center": 0.3, "label": "ضعيف"},
    {"center": 0.6, "label": "متوسط"},
    {"center": 1.0, "label": "قوي"},
]
N_CLASSES = len(CLASSES)

# ========== معاملات NCO (مطابقة لـ v2) ==========
N_OSC      = 6           # مذبذبات لكل خزان
TH         = 2**30       # عتبة 32-bit
OFFSET     = TH // 2     # إعادة الضبط
F_WORD_BASE = 2**28      # كلمة التردد الأساسية
NOISE_STD  = TH // 4     # ضوضاء رقمية
DRIVE_SCALE = 2          # تضخيم الإشارة الداخلة

# عتبات مختلفة لكل مذبذب في الخزان
THS = [int(TH * (0.8 + 0.4 * i / N_OSC)) for i in range(N_OSC)]

# ========== عينات الاختبار ==========
SAMPLES_PER_CLASS = 100
TOTAL = N_CLASSES * SAMPLES_PER_CLASS
SIGMA = 0.06           # ضوضاء ±6%


class NCO:
    """مذبذب رقمي NCO (signed 32-bit) — مطابق لـ v2."""
    __slots__ = ('acc', 'th', 'offset', 'firing_dir', 'n_fires', 'seed', '_rng')
    def __init__(self, th, offset, seed):
        self.acc = 0
        self.th = th
        self.offset = offset
        self.firing_dir = 0
        self.n_fires = 0
        self.seed = seed
        self._rng = random.Random(seed)

    def step(self, fw):
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

    def reset(self):
        self.acc = 0
        self.firing_dir = 0
        self.n_fires = 0


class NCOBank:
    """خزان NCO واحد — 6 مذبذبات مخصصة لفئة واحدة."""

    def __init__(self, class_id, seed_base):
        self.class_id = class_id
        self.oscs = [NCO(THS[i], OFFSET, seed_base + i * 100)
                     for i in range(N_OSC)]

    def process_ttfs(self, signal_value, max_steps=100):
        """
        Time-to-First-Spike — يعمل حتى أول إطلاق.
        تعيد: (إطلاقات, عدد الخطوات حتى أول إطلاق, هل أطلق أحد؟)
        """
        for o in self.oscs:
            o.reset()

        fw = int(signal_value * TH)

        for step in range(1, max_steps + 1):
            for o in self.oscs:
                o.step(fw)
            # هل أي مذبذب أطلق؟
            if any(o.firing_dir != 0 for o in self.oscs):
                total_fires = sum(o.n_fires for o in self.oscs)
                return {
                    "fired": True,
                    "first_spike": step,
                    "total_fires": total_fires,
                    "pos_votes": sum(1 for o in self.oscs if o.firing_dir > 0),
                }

        return {
            "fired": False,
            "first_spike": max_steps,
            "total_fires": sum(o.n_fires for o in self.oscs),
            "pos_votes": 0,
        }


def _gen_signals():
    random.seed(42)
    signals = []
    expected = []
    for cls in range(N_CLASSES):
        for _ in range(SAMPLES_PER_CLASS):
            base = CLASSES[cls]["center"]
            noisy = base + random.gauss(0, SIGMA)
            signals.append(max(0.01, noisy))
            expected.append(cls)
    zipped = list(zip(signals, expected))
    random.shuffle(zipped)
    signals, expected = zip(*zipped)
    return list(signals), list(expected)


def run_experiment(max_steps=100):
    """تجربة تصنيف متعدد الفئات بـ Time-to-First-Spike."""
    random.seed(42)
    banks = [NCOBank(cid, seed_base=1000 + cid * 1000)
             for cid in range(N_CLASSES)]

    signals, expected = _gen_signals()
    correct = 0
    cm = [[0] * N_CLASSES for _ in range(N_CLASSES)]
    bank_stats = [{"fires": 0, "wins": 0, "total_steps": 0} for _ in range(N_CLASSES)]

    for i in range(TOTAL):
        results = [banks[cid].process_ttfs(signals[i], max_steps)
                   for cid in range(N_CLASSES)]

        # الخزان الذي أطلق أولاً هو الفائز
        fired = [(cid, results[cid]["first_spike"])
                 for cid in range(N_CLASSES) if results[cid]["fired"]]

        if fired:
            # الأسرع إطلاقاً
            fastest = min(fired, key=lambda x: x[1])
            # كسر التعادل (نفس السرعة) → مجموع الإطلاقات
            same_speed = [cid for cid, sp in fired if sp == fastest[1]]
            if len(same_speed) > 1:
                most_fires = max(results[cid]["total_fires"] for cid in same_speed)
                decision = [cid for cid in same_speed
                            if results[cid]["total_fires"] == most_fires][0]
            else:
                decision = fastest[0]
        else:
            # لم يطلق أحد — أقوى إشارة
            strengths = [signals[i] for _ in range(N_CLASSES)]
            decision = strengths.index(min(strengths))

        cm[expected[i]][decision] += 1
        bank_stats[decision]["wins"] += 1
        for cid in range(N_CLASSES):
            bank_stats[cid]["fires"] += results[cid]["total_fires"]
            bank_stats[cid]["total_steps"] += results[cid]["first_spike"]

        if decision == expected[i]:
            correct += 1

    accuracy = correct / TOTAL * 100
    return accuracy, cm, bank_stats


def print_results(max_steps, accuracy, cm, bank_stats):
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"Onyx V3 — NCO Ensemble (TTFS)  |  max_steps={max_steps}")
    print(sep)
    print(f"  الفئات: {N_CLASSES} ({', '.join(c['label'] for c in CLASSES)})")
    print(f"  ضوضاء: σ={SIGMA}")
    print(f"  عينات/فئة: {SAMPLES_PER_CLASS}, الإجمالي: {TOTAL}")
    print(f"  مذبذبات/خزان: {N_OSC},  خزانات: {N_CLASSES}")
    print(f"  إجمالي المذبذبات: {N_OSC * N_CLASSES}")
    print()
    print(f"  ✅ الدقة الكلية: {accuracy:.2f}% ({int(accuracy*TOTAL/100)}/{TOTAL})")
    print()

    print("  مصفوفة التشويش:")
    header = f"{'':>12}" + "".join(f"{c['label']:>10}" for c in CLASSES)
    print(header)
    for c in range(N_CLASSES):
        row = f"  متوقع {CLASSES[c]['label']:>5}"
        for p in range(N_CLASSES):
            row += f"{cm[c][p]:>10}"
        print(row)

    print()
    print("  إحصائيات الخزانات:")
    for cid in range(N_CLASSES):
        avg_steps = bank_stats[cid]['total_steps'] / SAMPLES_PER_CLASS if SAMPLES_PER_CLASS > 0 else 0
        print(f"    خزان {CLASSES[cid]['label']}: فوز={bank_stats[cid]['wins']}, "
              f"إطلاقات={bank_stats[cid]['fires']}, متوسط الزمن={avg_steps:.1f}")

    print(sep)


def main():
    N_STEPS_LIST = [2, 5, 10, 20, 50, 100]

    print(f"{'='*60}")
    print("🧪 Onyx V3 — NCO Ensemble (Multi-class)")
    print(f"{'='*60}")
    print(f"  {N_CLASSES} فئات, {N_OSC} مذبذبات/خزان = {N_OSC * N_CLASSES} إجمالي")
    print(f"  عتبة: 2^{int(math.log2(TH))}, F_Word: 2^{int(math.log2(F_WORD_BASE))}")
    print(f"  ضوضاء الاختبار: σ={SIGMA}")
    print()

    # جدول
    header = f"{'N_STEPS':>8} | {'Accuracy':>9} | {'فوز صحيح':>10} | {'إطلاقات':>9}"
    bar = '-' * len(header)
    print(header)
    print(bar)

    results = []
    for ns in N_STEPS_LIST:
        acc, cm, bs = run_experiment(ns)
        results.append((ns, acc, cm, bs))

        correct_count = int(acc * TOTAL / 100)
        total_fires = sum(b['fires'] for b in bs)
        print(f"{ns:>8} | {acc:>9.2f}% | {correct_count:>4}/{TOTAL:<4} | {total_fires:>9}")

    print(bar)

    # مقارنة
    print(f"\n{'='*60}")
    print("📊 المقارنة مع v1/v2")
    print(f"{'='*60}")
    print(f"{'':>15} {'v1 LIF':>10} {'v2 NCO':>10} {'v3 Ensemble':>14}")
    print(f"{'─'*50}")
    print(f"{'N_STEPS':>15} {'5':>10} {'2':>10} {'2-100':>14}")
    print(f"{'فئات (classes)':>15} {'2':>10} {'2':>10} {'3-5':>14}")
    print(f"{'مذبذبات':>15} {'6':>10} {'6':>10} {'18-30':>14}")
    print(f"{'دقة @ σ=0.06':>15} {'100%':>10} {'100%':>10} {'?':>14}")

    # أفضل نتيجة
    best = max(results, key=lambda x: x[1])
    print()
    print(f"  أفضل دقة: {best[1]:.2f}% عند N_STEPS={best[0]}")
    print()
    print_results(best[0], best[1], best[2], best[3])

    print(f"\n{'='*60}")
    print("✅ Onyx V3 — NCO Ensemble experiment complete.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
