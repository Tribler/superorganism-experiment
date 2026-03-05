"""
Dataset registry for Learning-to-Rank benchmarking.

Supports multiple public LTR datasets in LETOR/SVMLight format:
- MSLR-WEB10K (Microsoft, 136 features)
- MSLR-WEB30K (Microsoft, 136 features)
- Yahoo! LTRC (310 features)
- Istella LETOR (220 features)
- Istella-S LETOR (220 features, smaller)
- LETOR 4.0 MQ2007/MQ2008 (46 features)
- aol4foltr (103 features)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import numpy as np
from sklearn.datasets import load_svmlight_file


@dataclass
class DatasetInfo:
    """Metadata about a LTR dataset."""
    name: str
    num_features: int
    description: str
    download_url: str
    license: str
    has_folds: bool = True
    num_folds: int = 5
    relevance_levels: int = 5  # 0-4 typically


# Registry of known datasets
DATASET_REGISTRY: dict[str, DatasetInfo] = {
    "mslr-web10k": DatasetInfo(
        name="MSLR-WEB10K",
        num_features=136,
        description="Microsoft Learning to Rank dataset with 10K queries",
        download_url="https://www.microsoft.com/en-us/research/project/mslr/",
        license="Microsoft Research License",
        has_folds=True,
        num_folds=5,
    ),
    "mslr-web30k": DatasetInfo(
        name="MSLR-WEB30K",
        num_features=136,
        description="Microsoft Learning to Rank dataset with 30K queries",
        download_url="https://www.microsoft.com/en-us/research/project/mslr/",
        license="Microsoft Research License",
        has_folds=True,
        num_folds=5,
    ),
    "istella": DatasetInfo(
        name="Istella LETOR",
        num_features=220,
        description="Istella full LETOR dataset (10M+ examples)",
        download_url="https://istella.ai/datasets/letor-dataset/",
        license="Istella LETOR License (non-commercial)",
        has_folds=False,
        num_folds=1,
    ),
    "letor4-mq2008": DatasetInfo(
        name="LETOR 4.0 MQ2008",
        num_features=46,
        description="LETOR 4.0 Million Query 2008 dataset",
        download_url="https://www.microsoft.com/en-us/research/project/letor-learning-rank-information-retrieval/",
        license="Microsoft Research License",
        has_folds=True,
        num_folds=5,
    ),
    "aol4foltr": DatasetInfo(
        name="AOL4FOLTR",
        num_features=103,
        description="AOL query log dataset for federated LTR",
        download_url="https://zenodo.org/records/15689455",
        license="Research use",
        has_folds=False,
        num_folds=1,
        relevance_levels=2,  # Binary relevance
    ),
}


class LTRDataset:
    """
    Unified interface for loading LTR datasets in LETOR/SVMLight format.

    Handles caching, normalization, and train/vali/test splits.
    """

    def __init__(
        self,
        data_dir: Path | str,
        dataset_id: str | None = None,
        fold: int = 1,
        normalize: bool = False,
        max_queries: int | None = None,
    ):
        """
        Initialize dataset loader.

        Args:
            data_dir: Path to dataset directory
            dataset_id: Dataset identifier (for metadata lookup)
            fold: Fold number for cross-validation (1-indexed)
            normalize: Whether to normalize features
            max_queries: Maximum number of queries to load (for sampling large datasets)
        """
        self.data_dir = Path(data_dir)
        self.dataset_id = dataset_id
        self.fold = fold
        self.normalize = normalize
        self.max_queries = max_queries
        self._cache: dict[str, tuple] = {}
        self._scaler = None

        # Get dataset info if available
        self.info = DATASET_REGISTRY.get(dataset_id) if dataset_id else None

    def _get_split_path(self, split: str) -> Path:
        """Get path to a data split file."""
        # Try fold-based structure first (MSLR, LETOR 4.0)
        fold_path = self.data_dir / f"Fold{self.fold}" / f"{split}.txt"
        if fold_path.exists():
            return fold_path

        # Try flat structure
        flat_path = self.data_dir / f"{split}.txt"
        if flat_path.exists():
            return flat_path

        # Try "full" subdirectory (Istella)
        full_path = self.data_dir / "full" / f"{split}.txt"
        if full_path.exists():
            return full_path

        # Try with different naming conventions
        alt_names = {
            "vali": ["valid.txt", "validation.txt", "dev.txt", "full/vali.txt", "full/valid.txt"],
            "test": ["test.txt", "full/test.txt"],
            "train": ["train.txt", "full/train.txt", "letor.txt"],  # aol4foltr uses letor.txt
        }
        for alt_name in alt_names.get(split, []):
            alt_path = self.data_dir / alt_name
            if alt_path.exists():
                return alt_path

        raise FileNotFoundError(f"Could not find {split} split in {self.data_dir}")

    def _load_split(self, split: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Load a data split, returning (X, y, qid, groups)."""
        cache_key = f"{split}_{self.fold}_{self.max_queries}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Check if this is a single-file dataset (no separate splits)
        try:
            filepath = self._get_split_path(split)
        except FileNotFoundError:
            # Try to load from single file and create splits
            return self._load_from_single_file(split)

        # For large files with max_queries, use streaming approach
        if self.max_queries is not None and split == "train":
            X, y, qid = self._load_svmlight_sampled(filepath, self.max_queries)
        else:
            X, y, qid = load_svmlight_file(str(filepath), query_id=True)
            X = X.toarray()

        # Replace inf/nan values and clip extreme values (for XGBoost compatibility)
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
        X = np.clip(X, -1e6, 1e6)

        # Normalize if requested
        if self.normalize:
            if split == "train":
                from sklearn.preprocessing import StandardScaler
                self._scaler = StandardScaler()
                X = self._scaler.fit_transform(X)
            elif self._scaler is not None:
                X = self._scaler.transform(X)

        groups = self._compute_groups(qid)
        self._cache[cache_key] = (X, y, qid, groups)
        return X, y, qid, groups

    def _load_from_single_file(self, split: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Load split from a single-file dataset by creating train/vali/test splits.

        Uses 70/10/20 split ratio based on query boundaries.
        """
        # Find the single data file
        single_file = self.data_dir / "letor.txt"
        if not single_file.exists():
            raise FileNotFoundError(f"Could not find {split} split in {self.data_dir}")

        # Load full dataset (with sampling if needed)
        cache_key = f"_full_{self.max_queries}"
        if cache_key not in self._cache:
            if self.max_queries is not None:
                X, y, qid = self._load_svmlight_sampled(single_file, self.max_queries)
            else:
                X, y, qid = load_svmlight_file(str(single_file), query_id=True)
                X = X.toarray()

            # Replace inf/nan values
            X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
            X = np.clip(X, -1e6, 1e6)

            groups = self._compute_groups(qid)
            self._cache[cache_key] = (X, y, qid, groups)

        X, y, qid, groups = self._cache[cache_key]

        # Split by queries: 70% train, 10% vali, 20% test
        n_queries = len(groups)
        train_end = int(n_queries * 0.7)
        vali_end = int(n_queries * 0.8)

        # Compute sample indices from query boundaries
        train_samples = sum(groups[:train_end])
        vali_samples = sum(groups[train_end:vali_end])

        if split == "train":
            X_split = X[:train_samples]
            y_split = y[:train_samples]
            qid_split = qid[:train_samples]
            groups_split = groups[:train_end]
        elif split == "vali":
            X_split = X[train_samples:train_samples + vali_samples]
            y_split = y[train_samples:train_samples + vali_samples]
            qid_split = qid[train_samples:train_samples + vali_samples]
            groups_split = groups[train_end:vali_end]
        else:  # test
            X_split = X[train_samples + vali_samples:]
            y_split = y[train_samples + vali_samples:]
            qid_split = qid[train_samples + vali_samples:]
            groups_split = groups[vali_end:]

        # Normalize if requested
        if self.normalize:
            if split == "train":
                from sklearn.preprocessing import StandardScaler
                self._scaler = StandardScaler()
                X_split = self._scaler.fit_transform(X_split)
            elif self._scaler is not None:
                X_split = self._scaler.transform(X_split)

        # Cache the result
        split_cache_key = f"{split}_{self.fold}_{self.max_queries}"
        result = (X_split, y_split, qid_split, groups_split)
        self._cache[split_cache_key] = result
        return result

    def _load_svmlight_sampled(self, filepath: Path, max_queries: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Load SVMLight file with query-based sampling for large datasets."""
        print(f"  Loading with max_queries={max_queries}...")

        # First pass: count queries and get their line ranges
        query_ranges = []
        current_qid = None
        start_line = 0

        with open(filepath, 'r') as f:
            for i, line in enumerate(f):
                # Parse qid from line (format: label qid:xxx ...)
                parts = line.strip().split()
                if len(parts) < 2:
                    continue
                qid_part = parts[1]
                if qid_part.startswith("qid:"):
                    qid = int(qid_part[4:])
                    if qid != current_qid:
                        if current_qid is not None:
                            query_ranges.append((current_qid, start_line, i))
                        current_qid = qid
                        start_line = i

                # Stop early if we have enough queries
                if len(query_ranges) >= max_queries:
                    break

            # Add the last query
            if current_qid is not None and len(query_ranges) < max_queries:
                query_ranges.append((current_qid, start_line, i + 1))

        print(f"  Found {len(query_ranges)} queries to load")

        # Sample queries if needed
        if len(query_ranges) > max_queries:
            np.random.seed(42)
            indices = np.random.choice(len(query_ranges), max_queries, replace=False)
            indices = sorted(indices)
            query_ranges = [query_ranges[i] for i in indices]

        # Second pass: load only the sampled lines
        lines_to_load = set()
        for _, start, end in query_ranges:
            lines_to_load.update(range(start, end))

        selected_lines = []
        with open(filepath, 'r') as f:
            for i, line in enumerate(f):
                if i in lines_to_load:
                    selected_lines.append(line)
                if i > max(lines_to_load):
                    break

        # Parse using sklearn from string
        from io import BytesIO
        content = '\n'.join(selected_lines).encode('utf-8')
        X, y, qid = load_svmlight_file(BytesIO(content), query_id=True)
        X = X.toarray()

        # Replace inf/nan values and clip extreme values (for XGBoost compatibility)
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
        X = np.clip(X, -1e6, 1e6)

        return X, y, qid

    @staticmethod
    def _compute_groups(qid: np.ndarray) -> np.ndarray:
        """Convert query IDs to group sizes for LightGBM/XGBoost."""
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
        """Load training data."""
        return self._load_split("train")

    def load_validation(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Load validation data."""
        return self._load_split("vali")

    def load_test(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Load test data."""
        return self._load_split("test")

    def load_all(self) -> dict[str, tuple]:
        """Load all splits."""
        return {
            "train": self.load_train(),
            "vali": self.load_validation(),
            "test": self.load_test(),
        }

    @property
    def num_features(self) -> int:
        """Get number of features (loads train if not cached)."""
        X, _, _, _ = self.load_train()
        return X.shape[1]

    @property
    def num_queries(self) -> dict[str, int]:
        """Get number of queries per split."""
        result = {}
        for split in ["train", "vali", "test"]:
            try:
                _, _, _, groups = self._load_split(split)
                result[split] = len(groups)
            except FileNotFoundError:
                pass
        return result


def get_dataset(
    dataset_id: str,
    base_dir: Path | str = "data",
    fold: int = 1,
    normalize: bool = False,
    max_queries: int | None = None,
) -> LTRDataset:
    """
    Get a dataset by ID from the registry.

    Args:
        dataset_id: Dataset identifier (e.g., "mslr-web10k")
        base_dir: Base directory containing datasets
        fold: Fold number (1-indexed)
        normalize: Whether to normalize features
        max_queries: Maximum number of queries to load (for sampling large datasets)

    Returns:
        LTRDataset instance
    """
    if dataset_id not in DATASET_REGISTRY:
        available = ", ".join(DATASET_REGISTRY.keys())
        raise ValueError(f"Unknown dataset: {dataset_id}. Available: {available}")

    info = DATASET_REGISTRY[dataset_id]

    # Map dataset ID to directory name
    dir_map = {
        "mslr-web10k": "MSLR-WEB10K",
        "mslr-web30k": "MSLR-WEB30K",
        "istella": "Istella",
        "letor4-mq2008": "MQ2008",
        "aol4foltr": "aol4foltr",
    }

    data_dir = Path(base_dir) / dir_map.get(dataset_id, dataset_id)
    return LTRDataset(data_dir, dataset_id, fold, normalize, max_queries)


def list_datasets() -> list[DatasetInfo]:
    """List all registered datasets."""
    return list(DATASET_REGISTRY.values())


def detect_datasets(base_dir: Path | str = "data") -> list[str]:
    """
    Detect which datasets are available locally.

    Args:
        base_dir: Base directory to search

    Returns:
        List of dataset IDs that are available
    """
    base_dir = Path(base_dir)
    available = []

    dir_to_id = {
        "MSLR-WEB10K": "mslr-web10k",
        "MSLR-WEB30K": "mslr-web30k",
        "Istella": "istella",
        "MQ2008": "letor4-mq2008",
        "aol4foltr": "aol4foltr",
    }

    for dir_name, dataset_id in dir_to_id.items():
        dataset_dir = base_dir / dir_name
        if dataset_dir.exists():
            # Check if it has actual data files
            has_data = (
                (dataset_dir / "Fold1" / "train.txt").exists() or
                (dataset_dir / "train.txt").exists() or
                (dataset_dir / "full" / "train.txt").exists() or
                (dataset_dir / "letor.txt").exists()  # aol4foltr single file
            )
            if has_data:
                available.append(dataset_id)

    return available


if __name__ == "__main__":
    # Detect and print available datasets
    print("Registered datasets:")
    for info in list_datasets():
        print(f"  - {info.name}: {info.num_features} features")

    print("\nDetecting local datasets...")
    data_dir = Path(__file__).parent / "data"
    available = detect_datasets(data_dir)
    print(f"Available locally: {available}")

    # Load and show stats for available datasets
    for dataset_id in available:
        print(f"\n{dataset_id}:")
        try:
            ds = get_dataset(dataset_id, data_dir)
            print(f"  Features: {ds.num_features}")
            print(f"  Queries: {ds.num_queries}")
        except Exception as e:
            print(f"  Error: {e}")
