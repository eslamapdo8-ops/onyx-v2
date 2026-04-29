import numpy as np
import sys

class CNNWeights:
    pass

cnn = CNNWeights()
cnn.W1 = np.random.randn(8, 1, 3, 3) * np.sqrt(2.0 / (1 * 9))
cnn.b1 = np.zeros(8)

print(f"W1 type={type(cnn.W1)} shape={cnn.W1.shape}", flush=True)
print(f"W1[0,0,0,0]={cnn.W1[0,0,0,0]}", flush=True)
print("ALL OK")
