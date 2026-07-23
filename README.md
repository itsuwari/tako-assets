# atomli-tako-ci

The Tako Code Interpreter runtime, packaged for PyPI, with a minimal slice of
the calculation WASM cores and model checkpoints bundled inside the wheel.

It is the `pip` sibling of the npm package `@atomli/tako-ci`. Sandboxes such as
ChatGPT Code Interpreter cannot fetch arbitrary URLs — the only inbound channel
is the package proxy — so Tako delivers its runtime and the assets it needs as an
installable package instead of an over-the-wire download.

## Install

```sh
pip install atomli-tako-ci
```

## Run a job

```sh
python3 -m tako_ci job.json --manifest runtime-manifest.json --output result.tako.zip
```

`job.json` and `runtime-manifest.json` are produced by Tako's `prepare_tako_script`
tool. The runner loads the WASM core (and, for MLIP/Skala jobs, the model
checkpoint), executes the calculation on a Node-compatible host (`node` or
`bun`), and writes a `result.tako.zip` bundle.

## What ships in the wheel

The runner (`tako_ci/tako_ci.py`) resolves every asset named in the runtime
manifest by first looking for a bundled copy under `tako_ci/assets/`, verifying
its SHA-256, and only falling back to a signed network download when the asset is
not present locally.

To stay within a git- and PyPI-friendly size (~28 MB), only the smallest cores
and checkpoints are bundled:

| Asset | Kind | Size | Runs |
| --- | --- | --- | --- |
| `mlip_core` | WASM core | 3.0 MB | NequIP / Nequix models |
| `qc_core` | WASM core | 13 MB | Skala functional |
| `nequix-mp-1` | model | 2.8 MB | MLIP |
| `nequix-mp-1-pft` | model | 2.8 MB | MLIP |
| `nequip-s` | model | 5.6 MB | MLIP |
| `skala-1.1` | model | 2.4 MB | QC (DFT surrogate) |

Larger assets — the `tb_core` core, the `nequip-l` checkpoint (72 MB), and the
`equiformer` / `equiformer-gradient` checkpoints (486–560 MB) — are **not**
bundled. Jobs that need them fetch them over the network in hosts that allow it;
in fetch-restricted sandboxes those jobs run in the full Tako application
instead.

Bundled digests are pinned in `tako_ci/manifest.json`.
