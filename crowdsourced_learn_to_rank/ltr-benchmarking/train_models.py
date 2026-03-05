"""
Unified model training script for Learning-to-Rank benchmarking.

Trains multiple model types (XGBoost, LightGBM, Linear) on multiple datasets.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from datasets import LTRDataset, get_dataset, detect_datasets, DATASET_REGISTRY
from ltr_evaluator import ModelMetadata, NDCGEvaluator


def train_xgboost(
    X_train: np.ndarray,
    y_train: np.ndarray,
    groups_train: np.ndarray,
    X_vali: np.ndarray,
    y_vali: np.ndarray,
    groups_vali: np.ndarray,
    **kwargs,
):
    """Train an XGBoost ranking model."""
    import xgboost as xgb

    dtrain = xgb.DMatrix(X_train, label=y_train)
    dtrain.set_group(groups_train)

    dvalid = xgb.DMatrix(X_vali, label=y_vali)
    dvalid.set_group(groups_vali)

    params = {
        "objective": "rank:ndcg",
        "eval_metric": "ndcg@10",
        "eta": kwargs.get("learning_rate", 0.1),
        "max_depth": kwargs.get("max_depth", 6),
        "min_child_weight": kwargs.get("min_child_weight", 1),
        "subsample": kwargs.get("subsample", 0.8),
        "colsample_bytree": kwargs.get("colsample_bytree", 0.8),
        "seed": kwargs.get("seed", 42),
        "verbosity": 1,
    }

    num_rounds = kwargs.get("num_rounds", 500)
    early_stopping = kwargs.get("early_stopping", 50)

    model = xgb.train(
        params,
        dtrain,
        num_boost_round=num_rounds,
        evals=[(dtrain, "train"), (dvalid, "valid")],
        early_stopping_rounds=early_stopping,
        verbose_eval=50,
    )

    return model


def train_lightgbm(
    X_train: np.ndarray,
    y_train: np.ndarray,
    groups_train: np.ndarray,
    X_vali: np.ndarray,
    y_vali: np.ndarray,
    groups_vali: np.ndarray,
    **kwargs,
):
    """Train a LightGBM LambdaMART model."""
    import lightgbm as lgb

    train_data = lgb.Dataset(X_train, label=y_train, group=groups_train)
    valid_data = lgb.Dataset(X_vali, label=y_vali, group=groups_vali, reference=train_data)

    params = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "ndcg_eval_at": [1, 3, 5, 10],
        "learning_rate": kwargs.get("learning_rate", 0.05),
        "num_leaves": kwargs.get("num_leaves", 31),
        "max_depth": kwargs.get("max_depth", -1),
        "min_data_in_leaf": kwargs.get("min_data_in_leaf", 20),
        "feature_fraction": kwargs.get("feature_fraction", 0.8),
        "bagging_fraction": kwargs.get("bagging_fraction", 0.8),
        "bagging_freq": kwargs.get("bagging_freq", 5),
        "seed": kwargs.get("seed", 42),
        "verbose": 1,
    }

    num_rounds = kwargs.get("num_rounds", 500)
    early_stopping = kwargs.get("early_stopping", 50)

    callbacks = [
        lgb.early_stopping(stopping_rounds=early_stopping),
        lgb.log_evaluation(period=50),
    ]

    model = lgb.train(
        params,
        train_data,
        num_boost_round=num_rounds,
        valid_sets=[train_data, valid_data],
        valid_names=["train", "valid"],
        callbacks=callbacks,
    )

    return model


def train_linear(
    X_train: np.ndarray,
    y_train: np.ndarray,
    groups_train: np.ndarray,
    X_vali: np.ndarray,
    y_vali: np.ndarray,
    groups_vali: np.ndarray,
    **kwargs,
):
    """
    Train a simple linear ranker using coordinate ascent on NDCG.

    This is a basic pairwise approach that learns linear weights.
    """
    from sklearn.linear_model import Ridge

    # Use Ridge regression as a simple baseline
    # Maps relevance scores directly
    model = Ridge(alpha=kwargs.get("alpha", 1.0))
    model.fit(X_train, y_train)

    return model


def _ndcg_at_k(y_true: np.ndarray, scores: np.ndarray, k: int = 10) -> float:
    """Compute NDCG@k for a single query."""
    order = np.argsort(-scores)
    y_sorted = y_true[order]
    gains = 2**y_sorted - 1
    discounts = np.log2(np.arange(2, len(gains) + 2))
    dcg = np.sum(gains[:k] / discounts[:k])
    ideal_order = np.argsort(-y_true)
    ideal_gains = 2**y_true[ideal_order] - 1
    idcg = np.sum(ideal_gains[:k] / discounts[:k])
    return dcg / idcg if idcg > 0 else 0.0


def _eval_ndcg(weights: np.ndarray, X: np.ndarray, y: np.ndarray, groups: np.ndarray, k: int = 10) -> float:
    """Compute mean NDCG@k across all queries."""
    scores = X @ weights
    ndcgs = []
    start = 0
    for g in groups:
        end = start + g
        if g > 1:
            ndcgs.append(_ndcg_at_k(y[start:end], scores[start:end], k))
        start = end
    return np.mean(ndcgs) if ndcgs else 0.0


def train_pdgd(
    X_train: np.ndarray,
    y_train: np.ndarray,
    groups_train: np.ndarray,
    X_vali: np.ndarray,
    y_vali: np.ndarray,
    groups_vali: np.ndarray,
    **kwargs,
):
    """
    Train a linear ranker using Pairwise Differentiable Gradient Descent.

    For each query, samples document pairs with different relevance labels
    and updates weights via SGD on a sigmoid pairwise loss.
    """
    rng = np.random.default_rng(kwargs.get("seed", 42))
    num_features = X_train.shape[1]
    num_epochs = kwargs.get("num_epochs", 50)
    lr = kwargs.get("learning_rate", 0.001)
    pairs_per_query = kwargs.get("pairs_per_query", 50)
    patience = kwargs.get("patience", 10)

    weights = rng.normal(0, 0.01, size=num_features)

    # Precompute query boundaries
    boundaries = []
    start = 0
    for g in groups_train:
        boundaries.append((start, start + g))
        start += g

    best_ndcg = -1.0
    best_weights = weights.copy()
    no_improve = 0

    for epoch in range(num_epochs):
        # Shuffle query order each epoch
        query_order = rng.permutation(len(boundaries))

        for qi in query_order:
            s, e = boundaries[qi]
            X_q = X_train[s:e]
            y_q = y_train[s:e]
            n_docs = e - s

            if n_docs < 2:
                continue

            scores_q = X_q @ weights

            # Find indices where labels differ for efficient pair sampling
            unique_labels = np.unique(y_q)
            if len(unique_labels) < 2:
                continue

            # Sample pairs
            grad_accum = np.zeros(num_features)
            n_pairs = 0

            for _ in range(pairs_per_query):
                i, j = rng.integers(0, n_docs, size=2)
                if y_q[i] == y_q[j]:
                    continue

                # Ensure i is the more relevant doc
                if y_q[i] < y_q[j]:
                    i, j = j, i

                score_diff = scores_q[i] - scores_q[j]
                # Clamp for numerical stability
                score_diff = np.clip(score_diff, -30, 30)
                sigmoid = 1.0 / (1.0 + np.exp(-score_diff))

                # Gradient of -log(sigmoid(s_i - s_j))
                grad_accum += (sigmoid - 1.0) * (X_q[i] - X_q[j])
                n_pairs += 1

            if n_pairs > 0:
                weights -= lr * (grad_accum / n_pairs)

        # Evaluate on validation set
        val_ndcg = _eval_ndcg(weights, X_vali, y_vali, groups_vali)
        print(f"  Epoch {epoch+1}/{num_epochs}: val NDCG@10 = {val_ndcg:.4f}")

        if val_ndcg > best_ndcg:
            best_ndcg = val_ndcg
            best_weights = weights.copy()
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= patience:
                print(f"  Early stopping at epoch {epoch+1} (best val NDCG@10 = {best_ndcg:.4f})")
                break

    print(f"  Best val NDCG@10 = {best_ndcg:.4f}")
    return best_weights


class LinearRankerWrapper:
    """Wrapper to make sklearn models compatible with our interface."""

    def __init__(self, model):
        self.model = model
        self.weights = model.coef_

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)

    def save(self, path: str):
        np.save(path, self.weights)


def save_model(
    model,
    model_type: str,
    output_path: Path,
    dataset_name: str,
    description: str = "",
):
    """Save model with metadata."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save model
    if model_type == "xgboost":
        model.save_model(str(output_path))
    elif model_type == "lightgbm":
        model.save_model(str(output_path))
    elif model_type in ("linear", "pdgd"):
        if hasattr(model, "weights"):
            np.save(str(output_path), model.weights)
        else:
            np.save(str(output_path), model.coef_)
    else:
        raise ValueError(f"Unknown model type: {model_type}")

    # Save metadata
    metadata = ModelMetadata(
        type=model_type if model_type not in ("linear", "pdgd") else "custom",
        name=f"{model_type.upper()} on {dataset_name}",
        version="1.0.0",
        created=datetime.now(timezone.utc).isoformat(),
        description=description or f"Trained on {dataset_name}",
        predict_script="pdgd_handler.py" if model_type in ("linear", "pdgd") else "",
    )
    metadata.save(output_path)

    print(f"Saved: {output_path}")
    return output_path


def train_on_dataset(
    dataset_id: str,
    model_type: str,
    output_dir: Path,
    data_dir: Path,
    fold: int = 1,
    **train_kwargs,
) -> Path:
    """
    Train a model on a specific dataset.

    Args:
        dataset_id: Dataset identifier
        model_type: "xgboost", "lightgbm", or "linear"
        output_dir: Directory to save models
        data_dir: Directory containing datasets
        fold: Fold number for cross-validation
        **train_kwargs: Additional training parameters

    Returns:
        Path to saved model
    """
    print(f"\n{'='*60}")
    print(f"Training {model_type.upper()} on {dataset_id} (fold {fold})")
    print(f"{'='*60}")

    # Large datasets need sampling
    max_queries = train_kwargs.pop("max_queries", None)
    if dataset_id == "aol4foltr" and max_queries is None:
        max_queries = 10000  # Default: sample 10K queries from aol4foltr

    # Load dataset
    dataset = get_dataset(dataset_id, data_dir, fold=fold, max_queries=max_queries)
    X_train, y_train, qid_train, groups_train = dataset.load_train()

    # Try to load validation, fall back to splitting train if not available
    try:
        X_vali, y_vali, _, groups_vali = dataset.load_validation()
        print(f"Train: {X_train.shape[0]} samples, {len(groups_train)} queries")
        print(f"Valid: {X_vali.shape[0]} samples, {len(groups_vali)} queries")
    except FileNotFoundError:
        # No validation split - use last 20% of queries for validation
        print("No validation split found, splitting training data...")
        n_train_queries = int(len(groups_train) * 0.8)
        train_end = sum(groups_train[:n_train_queries])

        X_vali = X_train[train_end:]
        y_vali = y_train[train_end:]
        groups_vali = groups_train[n_train_queries:]

        X_train = X_train[:train_end]
        y_train = y_train[:train_end]
        groups_train = groups_train[:n_train_queries]

        print(f"Train: {X_train.shape[0]} samples, {len(groups_train)} queries")
        print(f"Valid: {X_vali.shape[0]} samples, {len(groups_vali)} queries")

    # Train model
    train_fn = {
        "xgboost": train_xgboost,
        "lightgbm": train_lightgbm,
        "linear": train_linear,
        "pdgd": train_pdgd,
    }[model_type]

    model = train_fn(
        X_train, y_train, groups_train,
        X_vali, y_vali, groups_vali,
        **train_kwargs,
    )

    # Wrap linear model
    if model_type == "linear":
        model = LinearRankerWrapper(model)
    elif model_type == "pdgd":
        model = LinearRankerWrapper(type("_W", (), {"coef_": model, "predict": lambda self, X: X @ self.coef_})())

    # Determine output path
    ext = {"xgboost": ".json", "lightgbm": ".txt", "linear": ".npy", "pdgd": ".npy"}[model_type]
    output_path = output_dir / f"{dataset_id}_{model_type}{ext}"

    # Save model
    save_model(
        model,
        model_type,
        output_path,
        dataset_id,
        f"Trained on {dataset_id} fold {fold}",
    )

    return output_path


def train_all_models(
    dataset_ids: list[str],
    model_types: list[str],
    output_dir: Path,
    data_dir: Path,
    fold: int = 1,
):
    """Train all specified models on all specified datasets."""
    results = []

    for dataset_id in dataset_ids:
        for model_type in model_types:
            try:
                output_path = train_on_dataset(
                    dataset_id,
                    model_type,
                    output_dir,
                    data_dir,
                    fold,
                )
                results.append({
                    "dataset": dataset_id,
                    "model": model_type,
                    "path": str(output_path),
                    "status": "success",
                })
            except Exception as e:
                print(f"Error training {model_type} on {dataset_id}: {e}")
                results.append({
                    "dataset": dataset_id,
                    "model": model_type,
                    "status": "failed",
                    "error": str(e),
                })

    return results


def main():
    parser = argparse.ArgumentParser(description="Train LTR models on multiple datasets")
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=None,
        help="Dataset IDs to train on (default: all available)",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=["xgboost", "lightgbm"],
        choices=["xgboost", "lightgbm", "linear", "pdgd"],
        help="Model types to train",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent / "data",
        help="Directory containing datasets",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "models",
        help="Directory to save trained models",
    )
    parser.add_argument(
        "--fold",
        type=int,
        default=1,
        help="Fold number for cross-validation",
    )
    parser.add_argument(
        "--num-rounds",
        type=int,
        default=500,
        help="Number of boosting rounds",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=0.05,
        help="Learning rate",
    )

    args = parser.parse_args()

    # Detect available datasets if not specified
    if args.datasets is None:
        args.datasets = detect_datasets(args.data_dir)
        if not args.datasets:
            print("No datasets found. Please download datasets to the data directory.")
            print("\nAvailable datasets:")
            for name, info in DATASET_REGISTRY.items():
                print(f"  {name}: {info.download_url}")
            return

    print(f"Datasets: {args.datasets}")
    print(f"Models: {args.models}")
    print(f"Data dir: {args.data_dir}")
    print(f"Output dir: {args.output_dir}")

    # Train all models
    results = train_all_models(
        args.datasets,
        args.models,
        args.output_dir,
        args.data_dir,
        args.fold,
    )

    # Print summary
    print("\n" + "=" * 60)
    print("TRAINING SUMMARY")
    print("=" * 60)
    for r in results:
        status = "[OK]" if r["status"] == "success" else "[FAIL]"
        print(f"  {status} {r['dataset']} / {r['model']}")
        if r["status"] == "failed":
            print(f"      Error: {r.get('error', 'unknown')}")

    # Save results
    results_path = args.output_dir / "training_results.json"
    with open(results_path, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "datasets": args.datasets,
            "models": args.models,
            "results": results,
        }, f, indent=2)
    print(f"\nResults saved: {results_path}")


if __name__ == "__main__":
    main()
