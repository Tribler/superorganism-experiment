"""Custom model handler for LightGBM."""

import numpy as np


def load(model_path: str):
    import lightgbm as lgb
    return lgb.Booster(model_file=model_path)


def predict(model, X: np.ndarray) -> np.ndarray:
    return model.predict(X)