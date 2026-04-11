import numpy as np
from CANONICAL_FEATURE_PIPELINE import build_feature_result_from_v7
from rules.canonical import evaluate_all_rules

snap, result = build_feature_result_from_v7('snapshots_raw_ws_features_v7.npz', start=0, end=1000)
merged = result.merged()
merged["chain_gap_abs"] = merged["chain_gap"] # dummy or real if exist

masks = evaluate_all_rules(merged)
for k, v in masks.items():
    print(f"{k}: {v.sum()} triggers")
