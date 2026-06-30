import sys
import os
from cx_Freeze import setup, Executable

base = "Win32GUI" if sys.platform == "win32" else None

submodule_path = os.path.abspath("torrent_health_and_investment")
sys.path.append(submodule_path)

include_files = [
    ("logging_config.json", "logging_config.json"),
    ("ui/", "ui/"),
    ("libsodium.dll", "libsodium.dll"),
    ("crowdsourced_learn_to_rank/ltr-benchmarking/", "ltr-benchmarking/"),
]

packages = [
    "aiohttp",
    "bencodepy",
    "cryptography",
    "httpx",
    "libnacl",
    "libtorrent",
    "ipv8",
    "PySide6",
    "matplotlib",
    "numpy",
    "sklearn",
    "lightgbm",
    "xgboost"
]

build_exe_options = {
    "include_files": include_files,
    "packages": packages,
    "include_path": [submodule_path],
    "zip_includes": [
        ("torrent_health_and_investment/healthchecker/", "healthchecker/"),
        ("crowdsourced_learn_to_rank/ltr-benchmarking/", "crowdsourced_learn_to_rank/ltr-benchmarking/"),
        ("crowdsourced_learn_to_rank/", "crowdsourced_learn_to_rank/"),
    ],
    "excludes": ["tkinter", "unittest", "email", "http.server"],
}

setup(
    options={"build_exe": build_exe_options},
    executables=[
        Executable(
            "main.py",
            base=base,
            target_name="SuperorganismExperiment.exe"
        )
    ],
)
