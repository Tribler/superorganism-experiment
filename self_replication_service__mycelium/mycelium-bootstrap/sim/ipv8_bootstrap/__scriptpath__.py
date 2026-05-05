# Vendored from Tribler/py-ipv8 scripts/__scriptpath__.py — see py-ipv8 docs §"Bootstrapping".
import pathlib
import sys

sys.path.insert(1, str(pathlib.Path(__file__, "..", "..").resolve()))
