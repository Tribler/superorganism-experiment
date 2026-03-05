"""
Model files should be accompanied by a .meta.json file with the following structure:
{
    "type": "lightgbm" | "xgboost" | "custom",
    "name": "Human-readable model name",
    "version": "1.0.0",
    "created": "2026-01-20T12:00:00Z",
    "author": "optional author name",
    "description": "optional description",
    "predict_script": "model_handler.py"  // Required for type="custom"
}

For custom models, the predict_script must define:
    - load(model_path: str) -> Any: Load and return the model
    - predict(model: Any, X: np.ndarray) -> np.ndarray: Return predictions
"""

import numpy as np
from sklearn.datasets import load_svmlight_file
from sklearn.metrics import ndcg_score
from pathlib import Path
from dataclasses import dataclass, field
from typing import Protocol, Any
import time
import json
import importlib.util
from datetime import datetime, timezone


class RankingModel(Protocol):
    """Protocol for ranking models. Any model with a predict method works."""

    def predict(self, X: np.ndarray) -> np.ndarray: ...


@dataclass
class EvalResult:
    """Results from evaluating a single model."""

    name: str
    ndcg_scores: dict[int, float]  # k -> NDCG@k
    eval_time: float

    def __str__(self) -> str:
        scores = " | ".join(f"NDCG@{k}: {v:.4f}" for k, v in sorted(self.ndcg_scores.items()))
        return f"{self.name}: {scores} (eval: {self.eval_time:.2f}s)"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "ndcg_scores": {str(k): v for k, v in self.ndcg_scores.items()},
            "eval_time": self.eval_time,
        }


@dataclass
class ComparisonResult:
    """Results from comparing two models."""

    baseline: EvalResult
    challenger: EvalResult
    k_values: list[int]

    @property
    def winner(self) -> str:
        """Determine winner based on NDCG@10 (or highest k)."""
        k = max(self.k_values)
        if self.challenger.ndcg_scores[k] > self.baseline.ndcg_scores[k]:
            return self.challenger.name
        return self.baseline.name

    @property
    def improvement(self) -> float:
        """Relative improvement of challenger over baseline at highest k."""
        k = max(self.k_values)
        baseline_score = self.baseline.ndcg_scores[k]
        challenger_score = self.challenger.ndcg_scores[k]
        return (challenger_score - baseline_score) / baseline_score

    def __str__(self) -> str:
        k = max(self.k_values)
        diff = self.challenger.ndcg_scores[k] - self.baseline.ndcg_scores[k]
        sign = "+" if diff >= 0 else ""
        return (
            f"Comparison: {self.baseline.name} vs {self.challenger.name}\n"
            f"  {self.baseline}\n"
            f"  {self.challenger}\n"
            f"  Winner (NDCG@{k}): {self.winner} ({sign}{diff:.4f}, {sign}{self.improvement:.2%})"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        k = max(self.k_values)
        return {
            "baseline": self.baseline.to_dict(),
            "challenger": self.challenger.to_dict(),
            "k_values": self.k_values,
            "winner": self.winner,
            "improvement": self.improvement,
            "primary_metric": f"NDCG@{k}",
        }

    def save(self, path: Path | str) -> Path:
        """Save comparison result to JSON file."""
        path = Path(path)
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "comparison": self.to_dict(),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path


class LETORDataset:
    """Handles loading and caching of LETOR-format datasets."""

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self._cache: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}

    def _load_split(self, split: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Load a data split, returning (X, y, qid, groups)."""
        if split in self._cache:
            return self._cache[split]

        filepath = self.data_dir / f"{split}.txt"
        X, y, qid = load_svmlight_file(str(filepath), query_id=True)
        X = X.toarray()
        groups = self._compute_groups(qid)

        self._cache[split] = (X, y, qid, groups)
        return X, y, qid, groups

    @staticmethod
    def _compute_groups(qid: np.ndarray) -> np.ndarray:
        """Convert query IDs to group sizes."""
        groups = []
        current_qid = None
        current_count = 0
        for q in qid:
            if q != current_qid:
                if current_qid is not None:
                    groups.append(current_count)
                current_qid = q
                current_count = 1
            else:
                current_count += 1
        groups.append(current_count)
        return np.array(groups)

    def load_train(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        return self._load_split("train")

    def load_validation(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        return self._load_split("vali")

    def load_test(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        return self._load_split("test")


class NDCGEvaluator:
    """Evaluates ranking models using NDCG metric (scikit-learn implementation)."""

    def __init__(self, k_values: list[int] | None = None):
        self.k_values = k_values or [1, 3, 5, 10]

    def evaluate_query_groups(
        self, y_true: np.ndarray, y_pred: np.ndarray, groups: np.ndarray, k: int
    ) -> float:
        """Calculate mean NDCG@k across all queries using sklearn."""
        scores = []
        start_idx = 0
        for group_size in groups:
            end_idx = start_idx + group_size
            y_true_q = y_true[start_idx:end_idx]
            y_pred_q = y_pred[start_idx:end_idx]

            # sklearn requires at least 2 documents to compute NDCG
            if len(y_true_q) > 1:
                score = ndcg_score([y_true_q], [y_pred_q], k=min(k, len(y_true_q)))
                scores.append(score)

            start_idx = end_idx
        return np.mean(scores) if scores else 0.0

    def evaluate(
        self,
        model: RankingModel,
        X: np.ndarray,
        y: np.ndarray,
        groups: np.ndarray,
        name: str = "model",
    ) -> EvalResult:
        """Evaluate a model and return results."""
        t0 = time.time()
        y_pred = model.predict(X)
        eval_time = time.time() - t0

        ndcg_scores = {}
        for k in self.k_values:
            ndcg_scores[k] = self.evaluate_query_groups(y, y_pred, groups, k)

        return EvalResult(name=name, ndcg_scores=ndcg_scores, eval_time=eval_time)

    def compare(
        self,
        baseline: RankingModel,
        challenger: RankingModel,
        X: np.ndarray,
        y: np.ndarray,
        groups: np.ndarray,
        baseline_name: str = "baseline",
        challenger_name: str = "challenger",
    ) -> ComparisonResult:
        """Compare two models and return results."""
        baseline_result = self.evaluate(baseline, X, y, groups, baseline_name)
        challenger_result = self.evaluate(challenger, X, y, groups, challenger_name)

        return ComparisonResult(
            baseline=baseline_result,
            challenger=challenger_result,
            k_values=self.k_values,
        )


class ModelWrapper:
    """Wraps various model types to provide a consistent predict interface."""

    def __init__(self, model, model_type: str = "auto"):
        self.model = model
        self.model_type = model_type

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.model_type == "xgboost":
            import xgboost as xgb
            return self.model.predict(xgb.DMatrix(X))
        elif self.model_type == "callable":
            return self.model(X)
        else:
            # Default: assume sklearn-like interface
            return self.model.predict(X)


@dataclass
class ModelMetadata:
    """Metadata for a saved model."""

    type: str  # "lightgbm", "xgboost", or "custom"
    name: str
    version: str = "1.0.0"
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    author: str = ""
    description: str = ""
    predict_script: str = ""  # Required for type="custom"

    def save(self, model_path: Path | str) -> Path:
        """Save metadata alongside a model file."""
        meta_path = Path(model_path).with_suffix(Path(model_path).suffix + ".meta.json")
        with open(meta_path, "w") as f:
            json.dump(self.__dict__, f, indent=2)
        return meta_path

    @classmethod
    def load(cls, model_path: Path | str) -> "ModelMetadata":
        """Load metadata for a model file."""
        path = Path(model_path)
        meta_path = path.with_suffix(path.suffix + ".meta.json")

        if not meta_path.exists():
            raise FileNotFoundError(
                f"No metadata file found at {meta_path}. "
                f"Create a .meta.json file with at least 'type' and 'name' fields."
            )

        with open(meta_path) as f:
            data = json.load(f)

        return cls(
            type=data["type"],
            name=data["name"],
            version=data.get("version", "1.0.0"),
            created=data.get("created", ""),
            author=data.get("author", ""),
            description=data.get("description", ""),
            predict_script=data.get("predict_script", ""),
        )


def load_lightgbm_model(path: Path | str) -> RankingModel:
    """Load a saved LightGBM model."""
    import lightgbm as lgb
    return lgb.Booster(model_file=str(path))


def load_xgboost_model(path: Path | str) -> ModelWrapper:
    """Load a saved XGBoost model."""
    import xgboost as xgb
    model = xgb.Booster()
    model.load_model(str(path))
    return ModelWrapper(model, model_type="xgboost")


class CustomModelWrapper:
    """
    Wraps a custom model loaded via a predict script.

    The predict script must define:
        - load(model_path: str) -> Any: Load and return the model
        - predict(model: Any, X: np.ndarray) -> np.ndarray: Return predictions
    """

    def __init__(self, model: Any, predict_fn: callable):
        self.model = model
        self.predict_fn = predict_fn

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.predict_fn(self.model, X)


def load_custom_model(model_path: Path | str, script_path: Path | str) -> CustomModelWrapper:
    """
    Load a custom model using its predict script.

    Args:
        model_path: Path to the model file
        script_path: Path to the Python script with load() and predict() functions

    Returns:
        CustomModelWrapper with the loaded model

    Raises:
        FileNotFoundError: If script doesn't exist
        AttributeError: If script doesn't define required functions
    """
    script_path = Path(script_path)
    if not script_path.exists():
        raise FileNotFoundError(f"Predict script not found: {script_path}")

    # Load the script as a module
    spec = importlib.util.spec_from_file_location("custom_model", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Validate required functions
    if not hasattr(module, "load"):
        raise AttributeError(f"Predict script must define a 'load' function: {script_path}")
    if not hasattr(module, "predict"):
        raise AttributeError(f"Predict script must define a 'predict' function: {script_path}")

    # Load the model and wrap it
    model = module.load(str(model_path))
    return CustomModelWrapper(model, module.predict)


def load_model(path: Path | str) -> tuple[RankingModel, ModelMetadata]:
    """
    Load any model using its metadata file.

    Args:
        path: Path to the model file (metadata file should be at path.meta.json)

    Returns:
        Tuple of (model, metadata)

    Raises:
        FileNotFoundError: If metadata file doesn't exist
        ValueError: If model type is not supported or custom model missing predict_script
    """
    path = Path(path)
    metadata = ModelMetadata.load(path)

    if metadata.type == "lightgbm":
        model = load_lightgbm_model(path)
    elif metadata.type == "xgboost":
        model = load_xgboost_model(path)
    elif metadata.type == "custom":
        if not metadata.predict_script:
            raise ValueError("Custom model type requires 'predict_script' in metadata")
        # Resolve script path relative to model file
        script_path = path.parent / metadata.predict_script
        model = load_custom_model(path, script_path)
    else:
        raise ValueError(f"Unsupported model type: {metadata.type}")

    return model, metadata


def save_model_with_metadata(
    model,
    path: Path | str,
    model_type: str,
    name: str,
    version: str = "1.0.0",
    author: str = "",
    description: str = "",
) -> tuple[Path, Path]:
    """
    Save a model along with its metadata file.

    Args:
        model: The model to save (LightGBM Booster or XGBoost Booster)
        path: Path to save the model
        model_type: "lightgbm" or "xgboost"
        name: Human-readable name for the model
        version: Version string
        author: Optional author name
        description: Optional description

    Returns:
        Tuple of (model_path, metadata_path)
    """
    path = Path(path)

    # Save model
    if model_type == "lightgbm":
        model.save_model(str(path))
    elif model_type == "xgboost":
        model.save_model(str(path))
    else:
        raise ValueError(f"Unsupported model type: {model_type}")

    # Save metadata
    metadata = ModelMetadata(
        type=model_type,
        name=name,
        version=version,
        author=author,
        description=description,
    )
    meta_path = metadata.save(path)

    return path, meta_path


# Convenience function for quick comparisons
def compare_models(
    baseline: RankingModel,
    challenger: RankingModel,
    data_dir: Path | str,
    baseline_name: str = "baseline",
    challenger_name: str = "challenger",
    k_values: list[int] | None = None,
    split: str = "test",
) -> ComparisonResult:
    """
    Compare two ranking models on a LETOR dataset.

    Args:
        baseline: The baseline model to compare against
        challenger: The model being evaluated
        data_dir: Path to LETOR dataset folder (containing train.txt, vali.txt, test.txt)
        baseline_name: Display name for baseline model
        challenger_name: Display name for challenger model
        k_values: List of k values for NDCG@k (default: [1, 3, 5, 10])
        split: Which data split to use ("train", "vali", or "test")

    Returns:
        ComparisonResult with evaluation metrics for both models
    """
    dataset = LETORDataset(data_dir)
    evaluator = NDCGEvaluator(k_values)

    if split == "train":
        X, y, _, groups = dataset.load_train()
    elif split == "vali":
        X, y, _, groups = dataset.load_validation()
    else:
        X, y, _, groups = dataset.load_test()

    return evaluator.compare(
        baseline, challenger, X, y, groups, baseline_name, challenger_name
    )


def compare_model_files(
    baseline_path: Path | str,
    challenger_path: Path | str,
    data_dir: Path | str,
    k_values: list[int] | None = None,
    split: str = "test",
) -> ComparisonResult:
    """
    Compare two model files using their metadata.

    Args:
        baseline_path: Path to baseline model file (must have .meta.json)
        challenger_path: Path to challenger model file (must have .meta.json)
        data_dir: Path to LETOR dataset folder
        k_values: List of k values for NDCG@k (default: [1, 3, 5, 10])
        split: Which data split to use ("train", "vali", or "test")

    Returns:
        ComparisonResult with evaluation metrics for both models
    """
    baseline, baseline_meta = load_model(baseline_path)
    challenger, challenger_meta = load_model(challenger_path)

    return compare_models(
        baseline=baseline,
        challenger=challenger,
        data_dir=data_dir,
        baseline_name=baseline_meta.name,
        challenger_name=challenger_meta.name,
        k_values=k_values,
        split=split,
    )


@dataclass
class BenchmarkResult:
    """Results from benchmarking multiple models."""

    results: list[EvalResult]
    dataset_name: str
    split: str
    k_values: list[int]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def ranking(self, k: int | None = None) -> list[EvalResult]:
        """Return results sorted by NDCG@k (descending)."""
        k = k or max(self.k_values)
        return sorted(self.results, key=lambda r: r.ndcg_scores[k], reverse=True)

    def __str__(self) -> str:
        k = max(self.k_values)
        lines = [
            f"Benchmark: {self.dataset_name} ({self.split})",
            f"Timestamp: {self.timestamp}",
            "-" * 60,
        ]
        for i, r in enumerate(self.ranking(k), 1):
            lines.append(f"  {i}. {r}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        k = max(self.k_values)
        return {
            "timestamp": self.timestamp,
            "dataset": self.dataset_name,
            "split": self.split,
            "k_values": self.k_values,
            "primary_metric": f"NDCG@{k}",
            "ranking": [r.to_dict() for r in self.ranking(k)],
        }

    def save(self, path: Path | str) -> Path:
        """Save benchmark result to JSON file."""
        path = Path(path)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path


def benchmark_models(
    model_paths: list[Path | str],
    data_dir: Path | str,
    dataset_name: str = "unknown",
    k_values: list[int] | None = None,
    split: str = "test",
    log_dir: Path | str | None = None,
) -> BenchmarkResult:
    """
    Benchmark multiple models on a dataset and optionally save results to file.

    Args:
        model_paths: List of paths to model files (must have .meta.json)
        data_dir: Path to LETOR dataset folder
        dataset_name: Name of the dataset (for logging)
        k_values: List of k values for NDCG@k (default: [1, 3, 5, 10])
        split: Which data split to use ("train", "vali", or "test")
        log_dir: Directory to save log file (default: None, no logging)

    Returns:
        BenchmarkResult with evaluation metrics for all models
    """
    dataset = LETORDataset(data_dir)
    evaluator = NDCGEvaluator(k_values)

    if split == "train":
        X, y, _, groups = dataset.load_train()
    elif split == "vali":
        X, y, _, groups = dataset.load_validation()
    else:
        X, y, _, groups = dataset.load_test()

    results = []
    for model_path in model_paths:
        model_path = Path(model_path)
        if not model_path.exists():
            print(f"Skipping {model_path} (not found)")
            continue
        model, metadata = load_model(model_path)
        result = evaluator.evaluate(model, X, y, groups, metadata.name)
        results.append(result)

    benchmark = BenchmarkResult(
        results=results,
        dataset_name=dataset_name,
        split=split,
        k_values=evaluator.k_values,
    )

    # Save log file if log_dir is specified
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"benchmark_{dataset_name}_{timestamp}.json"
        benchmark.save(log_path)
        print(f"Log saved: {log_path}")

    return benchmark


if __name__ == "__main__":
    # Example usage: compare models using metadata files
    models_dir = Path(__file__).parent / "models"
    data_dir = Path(__file__).parent / "data" / "MSLR-WEB30K" / "Fold1"

    lgb_path = models_dir / "lightgbm_lambdamart.txt"
    xgb_path = models_dir / "xgboost_ranking.json"

    # Check if metadata files exist, create them if not
    for path, model_type, name, desc in [
        (lgb_path, "lightgbm", "LightGBM LambdaMART", "LambdaMART trained on MSLR-WEB30K"),
        (xgb_path, "xgboost", "XGBoost Ranking", "XGBoost rank:ndcg trained on MSLR-WEB30K"),
    ]:
        meta_path = path.with_suffix(path.suffix + ".meta.json")
        if not meta_path.exists():
            print(f"Creating metadata file: {meta_path}")
            metadata = ModelMetadata(type=model_type, name=name, description=desc)
            metadata.save(path)

    print("Loading models via metadata...")
    result = compare_model_files(
        baseline_path=lgb_path,
        challenger_path=xgb_path,
        data_dir=data_dir,
    )

    print("\n" + "=" * 70)
    print(result)
    print("=" * 70)