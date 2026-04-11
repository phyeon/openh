import numpy as np
from CANONICAL_FEATURE_PIPELINE import build_feature_result_from_v7

snap, result = build_feature_result_from_v7("snapshots_raw_ws_features_v7.npz", start=0, end=100)
merged = result.merged()
print(sorted(list(merged.keys())))
