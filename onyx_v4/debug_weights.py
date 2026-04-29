import numpy as np
from sklearn.linear_model import RidgeClassifier, LogisticRegression

# Read features from hex (each value is 8-hex-char, parse manually)
with open('/workspaces/onyx-v2/onyx_v4/features_hex.txt') as f:
    lines = f.readlines()
features = np.zeros((len(lines), 16), dtype=np.int64)
for s, line in enumerate(lines):
    vals = line.strip().split()
    for d, v in enumerate(vals):
        features[s, d] = int(v, 16)
features_signed = np.where(features > 0x7FFFFFFF, features - 0x100000000, features)
print('Features range:', features_signed.min(), features_signed.max())

class NCO:
    def __init__(self, th=0.5):
        self.acc = 0
        self.th = int(th * (2**30))
        self.off = int(0.25 * (2**30))
        self.seed = 0xACE142BD
    def reset(self):
        self.acc = 0
        self.seed = 0xACE142BD
    def step(self, fw):
        fb = self.seed & 1
        self.seed = ((self.seed >> 1) | (fb << 31)) ^ (0xB4BCD35C if fb else 0)
        b0 = (self.seed >> 24) & 0xFF
        b1 = (self.seed >> 8) & 0xFF
        b2 = (self.seed << 8) & 0xFF0000
        b3 = (self.seed << 24) & 0xFF000000
        noise_s = (b0 | b1 | b2 | b3) >> 4
        self.acc = self.acc + fw + noise_s
        if self.acc > self.th:
            self.acc -= self.off
            return 1
        elif self.acc < -self.th:
            self.acc += self.off
            return -1
        return None

ncos = [NCO(th=0.5*(1+0.3*(i/16))) for i in range(16)]
fingerprints = np.zeros((50, 16), dtype=np.int8)
for s in range(50):
    for d in range(16):
        ncos[d].reset()
        for _ in range(3):
            ddir = ncos[d].step(features_signed[s, d])
            if ddir is not None:
                fingerprints[s, d] = ddir

print('Fingerprints unique:', np.unique(fingerprints, return_counts=True))

y = np.array([0]*25 + [1]*25)

for name, clf in [('Ridge(alpha=1.0)', RidgeClassifier(alpha=1.0)),
                   ('Ridge(alpha=0.01)', RidgeClassifier(alpha=0.01)),
                   ('LogReg(C=1e6)', LogisticRegression(C=1e6, solver='lbfgs'))]:
    clf.fit(fingerprints, y)
    c_ = clf.coef_
    print(f'{name}: coef_ range=[{c_.min():.4f}, {c_.max():.4f}], acc={clf.score(fingerprints, y)*100:.1f}%')
    if c_.ndim == 1:
        print(f'  coef_[:5]: {c_[:5]}')
    else:
        print(f'  coef_[0,:5]: {c_[0,:5]}')
