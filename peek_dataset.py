import numpy as np
data = np.load('/Users/hyeon/Projects/openh_gemini/basin_dataset.npz', allow_pickle=True)
print("Keys:", data.files)
print("X shape:", data['X'].shape)
print("mid shape:", data['mid'].shape)
print("rule_labels[:10]:", data['rule_labels'][:10])
print("t0_indices[:10]:", data['t0_indices'][:10])
