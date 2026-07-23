"""atomli-tako-ci — Tako Code Interpreter runtime and minimal calculation assets.

This package ships the portable Tako runner (``tako_ci.py`` + ``run.mjs``) and a
git/PyPI-sized slice of the calculation WASM cores and model checkpoints. The
runner discovers the bundled files under ``assets/`` and falls back to a signed
network download only for assets that are too large to distribute here.
"""

from .tako_ci import main

__all__ = ["main"]
