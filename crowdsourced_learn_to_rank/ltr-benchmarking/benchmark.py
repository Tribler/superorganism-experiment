"""
Benchmark script for evaluating LTR models across multiple datasets.

Creates a leaderboard showing model performance (NDCG@k) for each dataset.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np

from datasets import get_dataset, detect_datasets, DATASET_REGISTRY
from ltr_evaluator import load_model, NDCGEvaluator, EvalResult


@dataclass
class LeaderboardEntry:
    """Single entry in the leaderboard."""
    model_name: str
    model_path: str
    dataset: str
    ndcg_scores: dict[int, float]
    eval_time: float

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "model_path": self.model_path,
            "dataset": self.dataset,
            "ndcg_scores": {str(k): v for k, v in self.ndcg_scores.items()},
            "eval_time": self.eval_time,
        }


@dataclass
class Leaderboard:
    """Leaderboard tracking model performance across datasets."""
    entries: list[LeaderboardEntry] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    k_values: list[int] = field(default_factory=lambda: [1, 3, 5, 10])

    def add_entry(self, entry: LeaderboardEntry):
        self.entries.append(entry)

    def get_ranking(self, dataset: str, k: int = 10) -> list[LeaderboardEntry]:
        """Get entries for a dataset, sorted by NDCG@k."""
        dataset_entries = [e for e in self.entries if e.dataset == dataset]
        return sorted(dataset_entries, key=lambda e: e.ndcg_scores.get(k, 0), reverse=True)

    def get_model_performance(self, model_name: str) -> dict[str, dict[int, float]]:
        """Get a model's performance across all datasets."""
        return {
            e.dataset: e.ndcg_scores
            for e in self.entries
            if e.model_name == model_name
        }

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "k_values": self.k_values,
            "entries": [e.to_dict() for e in self.entries],
        }

    def save(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path | str) -> "Leaderboard":
        with open(path) as f:
            data = json.load(f)
        lb = cls(
            timestamp=data["timestamp"],
            k_values=data["k_values"],
        )
        for entry_data in data["entries"]:
            lb.entries.append(LeaderboardEntry(
                model_name=entry_data["model_name"],
                model_path=entry_data["model_path"],
                dataset=entry_data["dataset"],
                ndcg_scores={int(k): v for k, v in entry_data["ndcg_scores"].items()},
                eval_time=entry_data["eval_time"],
            ))
        return lb

    def print_table(self, k: int = 10):
        """Print leaderboard as a formatted table."""
        datasets = sorted(set(e.dataset for e in self.entries))

        for dataset in datasets:
            print(f"\n{'='*70}")
            print(f"Dataset: {dataset}")
            print(f"{'='*70}")
            print(f"{'Rank':<5} {'Model':<30} {'NDCG@1':<10} {'NDCG@5':<10} {'NDCG@10':<10}")
            print("-" * 70)

            for rank, entry in enumerate(self.get_ranking(dataset, k), 1):
                ndcg1 = entry.ndcg_scores.get(1, 0)
                ndcg5 = entry.ndcg_scores.get(5, 0)
                ndcg10 = entry.ndcg_scores.get(10, 0)
                print(f"{rank:<5} {entry.model_name:<30} {ndcg1:<10.4f} {ndcg5:<10.4f} {ndcg10:<10.4f}")

    def print_cross_dataset_summary(self, k: int = 10):
        """Print summary of model performance across datasets."""
        models = sorted(set(e.model_name for e in self.entries))
        datasets = sorted(set(e.dataset for e in self.entries))

        print(f"\n{'='*80}")
        print(f"Cross-Dataset Summary (NDCG@{k})")
        print(f"{'='*80}")

        # Header
        header = f"{'Model':<25}"
        for ds in datasets:
            header += f" {ds[:12]:<12}"
        header += f" {'Avg':<8}"
        print(header)
        print("-" * 80)

        # Rows
        for model in models:
            perf = self.get_model_performance(model)
            row = f"{model:<25}"
            scores = []
            for ds in datasets:
                if ds in perf:
                    score = perf[ds].get(k, 0)
                    scores.append(score)
                    row += f" {score:<12.4f}"
                else:
                    row += f" {'N/A':<12}"
            if scores:
                row += f" {np.mean(scores):<8.4f}"
            print(row)


def discover_models(models_dir: Path) -> list[tuple[Path, str]]:
    """Discover all models with metadata files.

    Returns:
        List of (model_path, dataset_id) tuples
    """
    models = []
    for meta_file in models_dir.glob("*.meta.json"):
        # Handle double extensions like .txt.meta.json -> .txt
        model_path = Path(str(meta_file).replace(".meta.json", ""))
        if model_path.exists():
            # Extract dataset from filename (e.g., "mslr-web10k_xgboost.json" -> "mslr-web10k")
            name = model_path.stem
            if name.endswith(".txt") or name.endswith(".json"):
                name = Path(name).stem  # Remove second extension
            # Dataset is before the last underscore
            parts = name.rsplit("_", 1)
            dataset_id = parts[0] if len(parts) > 1 else None
            models.append((model_path, dataset_id))
    return models


def benchmark_model_on_dataset(
    model_path: Path,
    dataset_id: str,
    data_dir: Path,
    evaluator: NDCGEvaluator,
    fold: int = 1,
) -> LeaderboardEntry | None:
    """Benchmark a single model on a single dataset."""
    try:
        # Load model
        model, metadata = load_model(model_path)

        # Load dataset (sample large datasets)
        max_queries = 10000 if dataset_id == "aol4foltr" else None
        dataset = get_dataset(dataset_id, data_dir, fold=fold, max_queries=max_queries)
        X_test, y_test, _, groups_test = dataset.load_test()

        # Evaluate
        result = evaluator.evaluate(model, X_test, y_test, groups_test, metadata.name)

        return LeaderboardEntry(
            model_name=metadata.name,
            model_path=str(model_path),
            dataset=dataset_id,
            ndcg_scores=result.ndcg_scores,
            eval_time=result.eval_time,
        )
    except Exception as e:
        print(f"  Error evaluating {model_path} on {dataset_id}: {e}")
        return None


def run_benchmark(
    models_dir: Path,
    data_dir: Path,
    datasets: list[str] | None = None,
    model_paths: list[tuple[Path, str]] | None = None,
    fold: int = 1,
    k_values: list[int] | None = None,
) -> Leaderboard:
    """
    Run benchmark of all models on their matching datasets.

    Args:
        models_dir: Directory containing trained models
        data_dir: Directory containing datasets
        datasets: List of dataset IDs to benchmark (default: all available)
        model_paths: List of (model_path, dataset_id) tuples (default: discover all)
        fold: Fold number for evaluation
        k_values: List of k values for NDCG@k

    Returns:
        Leaderboard with results
    """
    k_values = k_values or [1, 3, 5, 10]
    evaluator = NDCGEvaluator(k_values)
    leaderboard = Leaderboard(k_values=k_values)

    # Discover datasets if not specified
    if datasets is None:
        datasets = detect_datasets(data_dir)

    # Discover models if not specified
    if model_paths is None:
        model_paths = discover_models(models_dir)

    # Filter models to only those matching requested datasets
    model_paths = [(p, ds) for p, ds in model_paths if ds in datasets]

    print(f"Datasets: {datasets}")
    print(f"Models: {[p.name for p, _ in model_paths]}")

    # Run benchmark - each model on its matching dataset only
    total = len(model_paths)
    current = 0

    for dataset_id in datasets:
        # Get models for this dataset
        dataset_models = [(p, ds) for p, ds in model_paths if ds == dataset_id]
        if not dataset_models:
            continue

        print(f"\nBenchmarking on {dataset_id}...")

        for model_path, _ in dataset_models:
            current += 1
            print(f"  [{current}/{total}] {model_path.name}...", end=" ")

            entry = benchmark_model_on_dataset(
                model_path, dataset_id, data_dir, evaluator, fold
            )

            if entry:
                leaderboard.add_entry(entry)
                print(f"NDCG@10={entry.ndcg_scores.get(10, 0):.4f}")
            else:
                print("FAILED")

    return leaderboard


def main():
    parser = argparse.ArgumentParser(description="Benchmark LTR models")
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=None,
        help="Dataset IDs to benchmark on (default: all available)",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path(__file__).parent / "models",
        help="Directory containing trained models",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent / "data",
        help="Directory containing datasets",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file for leaderboard JSON",
    )
    parser.add_argument(
        "--fold",
        type=int,
        default=1,
        help="Fold number for evaluation",
    )
    parser.add_argument(
        "--k",
        type=int,
        nargs="+",
        default=[1, 3, 5, 10],
        help="K values for NDCG@k",
    )

    args = parser.parse_args()

    # Run benchmark
    leaderboard = run_benchmark(
        args.models_dir,
        args.data_dir,
        args.datasets,
        fold=args.fold,
        k_values=args.k,
    )

    # Print results
    leaderboard.print_table()
    leaderboard.print_cross_dataset_summary()

    # Save results
    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = args.models_dir.parent / "logs" / f"benchmark_{timestamp}.json"

    leaderboard.save(output_path)
    print(f"\nLeaderboard saved: {output_path}")


if __name__ == "__main__":
    main()
