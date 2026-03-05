"""PDGD model handler for DART-live linear ranker."""

import numpy as np


class PDGDLinearRanker:
    def __init__(self, weights: np.ndarray):
        self.weights = weights

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.dot(X, self.weights)


def load(model_path: str) -> PDGDLinearRanker:
    return PDGDLinearRanker(np.load(model_path))


def predict(model: PDGDLinearRanker, X: np.ndarray) -> np.ndarray:
    return model.predict(X)