#!/usr/bin/env python3
"""
Onyx V3 — Staircase Threshold Comparator (الإصدار النهائي)
=============================================================
تصنيف متعدد الفئات بمقارن عتبات متدرج حتمي.

الدقة:
  - 100% عند ضوضاء σ ≤ 0.02
  - 96% عند ضوضاء σ = 0.06
  - 82% عند ضوضاء σ = 0.10

الطاقة: < 1 fJ لكل تصنيف (تقديري — مقارنة واحدة فقط)
الزمن: دورة ساعة واحدة
عدد المذبذبات: 0 (لا يحتاج مذبذبات — مقارنات فقط)
"""

import random

# ========== فئات الاختبار (5 فئات) ==========
CLASSES = [
    {"center": 0.10, "label": "ضعيف جداً"},
    {"center": 0.30, "label": "ضعيف"},
    {"center": 0.55, "label": "متوسط"},
    {"center": 0.80, "label": "قوي"},
    {"center": 1.10, "label": "قوي جداً"},
]
N_CLASSES = len(CLASSES)
SAMPLES_PER_CLASS = 200
TOTAL = N_CLASSES * SAMPLES_PER_CLASS

# ========== عتبات ابتدائية محسوبة ==========
def init_thresholds():
    th = []
    for i in range(N_CLASSES):
        c = CLASSES[i]["center"]
        if i == 0:
            lo, hi = 0.0, (c + CLASSES[i+1]["center"]) / 2
        elif i == N_CLASSES - 1:
            lo, hi = (CLASSES[i-1]["center"] + c) / 2, c * 1.5
        else:
            lo = (CLASSES[i-1]["center"] + c) / 2
            hi = (c + CLASSES[i+1]["center"]) / 2
        th.append((lo, hi))
    return th


def classify(value, thresholds):
    """إرجاع class_id (0..N_CLASSES-1)."""
    for class_id, (lo, hi) in enumerate(thresholds):
        if lo <= value < hi:
            return class_id
    # خارج النطاقات → الأقرب
    return min(range(N_CLASSES), key=lambda i:
               abs(value - CLASSES[i]["center"]))


def run_test(noise_std):
    """تجربة واحدة بمستوى ضوضاء معين."""
    random.seed(42)
    thresholds = init_thresholds()

    signals, expected = [], []
    for cls in range(N_CLASSES):
        for _ in range(SAMPLES_PER_CLASS):
            base = CLASSES[cls]["center"]
            signals.append(max(0.0, base + random.gauss(0, noise_std)))
            expected.append(cls)

    # خلط
    zipped = list(zip(signals, expected))
    random.shuffle(zipped)
    signals, expected = zip(*zipped)

    correct = 0
    cm = [[0] * N_CLASSES for _ in range(N_CLASSES)]

    for i in range(TOTAL):
        d = classify(signals[i], thresholds)
        cm[expected[i]][d] += 1
        if d == expected[i]:
            correct += 1

    return correct / TOTAL * 100, cm


def print_cm(cm):
    header = " " * 14 + "".join(f"{CLASSES[c]['label']:>10}" for c in range(N_CLASSES))
    print(header)
    for c in range(N_CLASSES):
        row = f"  متوقع {CLASSES[c]['label']:>6}"
        for p in range(N_CLASSES):
            row += f"{cm[c][p]:>10}"
        print(row)


def main():
    sep = "=" * 65
    print(sep)
    print("🧪 Onyx V3 — Staircase Threshold Comparator (النسخة النهائية)")
    print(sep)
    print(f"  الفئات: {N_CLASSES}")
    for c in CLASSES:
        print(f"    - {c['label']}: إشارة {c['center']}")
    print(f"  عينات/فئة: {SAMPLES_PER_CLASS}, الإجمالي: {TOTAL}")
    print()

    # جدول الضوضاء
    NOISE_LEVELS = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15]
    print(sep)
    print("📊 جدول الدقة مقابل الضوضاء")
    print(sep)
    print(f"{'الضوضاء σ':>12} | {'الدقة':>9} | {'الحالة':>12}")
    print("-" * 40)

    for noise in NOISE_LEVELS:
        acc, _ = run_test(noise)
        status = "✅ مثالي" if acc == 100.0 else ("🟡 مقبول" if acc >= 90 else "🔴 محدود")
        print(f"{noise:>10.2f}  | {acc:>7.2f}%  | {status:>12}")

    print("-" * 40)

    # تفصيل النتائج عند σ=0.06
    print()
    print(sep)
    print("🔍 تفصيل عند σ=0.06")
    print(sep)
    acc, cm = run_test(0.06)
    print(f"  الدقة: {acc:.2f}%")
    print("\n  مصفوفة التشويش:")
    print_cm(cm)

    # العتبات
    print(f"\n  العتبات:")
    for i, (lo, hi) in enumerate(init_thresholds()):
        print(f"    فئة {i} ({CLASSES[i]['label']}): [{lo:.4f}, {hi:.4f})")
    print()

    # المقارنة مع v1/v2
    print(sep)
    print("📊 المقارنة النهائية — جميع إصدارات Onyx")
    print(sep)
    print(f"{'':>14} | {'v1 LIF':>12} | {'v2 NCO':>12} | {'v3 طبقات':>12}")
    print("-" * 55)
    print(f"{'عدد الخطوات':>14} | {'5':>12} | {'2':>12} | {'1':>12}")
    print(f"{'فئات (classes)':>14} | {'2':>12} | {'2':>12} | {'5':>12}")
    print(f"{'الطاقة/تصنيف':>14} | {'0.87 pJ':>12} | {'~0.03 pJ':>12} | {'< 1 fJ':>12}")
    print(f"{'دقة @ σ=0.02':>14} | {'100%':>12} | {'100%':>12} | {'100%':>12}")
    print(f"{'دقة @ σ=0.06':>14} | {'100%':>12} | {'100%':>12} | {'~96%':>12}")
    print(f"{'نوع المذبذب':>14} | {'LIF':>12} | {'NCO':>12} | {'لا يوجد':>12}")
    print(f"{'ذاكرة زمنية':>14} | {'نعم':>12} | {'نعم':>12} | {'لا':>12}")
    print("-" * 55)
    print()

    # تقييم
    print(sep)
    print("✅ التقييم النهائي")
    print(sep)
    print("""
  Onyx V1 (LIF): تصنيف ثنائي، 100% دقة، 0.87 pJ — التصميم التماثلي
  Onyx V2 (NCO): تصنيف ثنائي، 100% دقة، 0.03 pJ — التصميم الرقمي المُوصى به ★
  Onyx V3 (Staircase): تصنيف متعدد الفئات (5 فئات)، 96% @ σ=0.06 — محدود الضوضاء

  الخلاصة:
  - للتصنيف الثنائي: استخدم Onyx V2 NCO (أعلى كفاءة، 100% دقة).
  - للتصنيف متعدد الفئات بضوضاء منخفضة: استخدم Onyx V3 Staircase.
  - للتصنيف متعدد الفئات بضوضاء عالية: يحتاج إلى معماريّة مختلفة.
""")


if __name__ == "__main__":
    main()
