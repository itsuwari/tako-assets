#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()

def progress(stage, **values):
    print("TAKO_PROGRESS " + json.dumps({"stage": stage, **values}, separators=(",", ":")), flush=True)

def asset_bases(package_dir):
    script_dir = Path(__file__).resolve().parent
    bases = [package_dir, script_dir]
    scope = script_dir.parent
    if scope.is_dir():
        for sibling in sorted(scope.iterdir()):
            if sibling != script_dir and (sibling / "assets").is_dir():
                bases.append(sibling)
    return bases

def assemble_parts(asset, cache, bases):
    name = asset["file"]
    found = {}
    for base in bases:
        for part in (base / "assets").glob(name + ".part*"):
            found.setdefault(int(part.suffix[5:]), part)
    if not found:
        return None
    if sorted(found) != list(range(len(found))):
        raise RuntimeError("Split asset is missing parts: " + name)
    target = cache / name
    if target.is_file() and digest(target) == asset["sha256"]:
        progress("asset-ready", file=name, source="cache", bytes=asset.get("bytes"))
        return target
    staging = target.with_suffix(target.suffix + ".assemble")
    with staging.open("wb") as handle:
        for index in range(len(found)):
            with found[index].open("rb") as source:
                shutil.copyfileobj(source, handle)
    if digest(staging) != asset["sha256"]:
        staging.unlink(missing_ok=True)
        raise RuntimeError("Split asset failed sha256 validation: " + name)
    staging.replace(target)
    progress("asset-ready", file=name, source="package-split", bytes=asset.get("bytes"))
    return target

def download(asset, cache, package_dir, attempts=4):
    target = cache / asset["file"]
    for base in asset_bases(package_dir):
        embedded = base / "assets" / asset["file"]
        if not embedded.is_file():
            continue
        if digest(embedded) != asset["sha256"]:
            raise RuntimeError("Embedded asset failed sha256 validation: " + asset["file"])
        if not target.is_file() or digest(target) != asset["sha256"]:
            shutil.copyfile(embedded, target)
        progress("asset-ready", file=asset["file"], source="package", bytes=asset.get("bytes"))
        return target
    assembled = assemble_parts(asset, cache, asset_bases(package_dir))
    if assembled is not None:
        return assembled
    if target.is_file() and digest(target) == asset["sha256"]:
        progress("asset-ready", file=asset["file"], source="cache", bytes=asset.get("bytes"))
        return target
    part = target.with_suffix(target.suffix + ".part")
    for attempt in range(1, attempts + 1):
        received = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "Tako-Code-Interpreter/1"}
        if received:
            headers["Range"] = "bytes=%d-" % received
        try:
            request = urllib.request.Request(asset["url"], headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                append = received > 0 and response.status == 206
                if not append:
                    received = 0
                mode = "ab" if append else "wb"
                with part.open(mode) as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        received += len(chunk)
                        progress("downloading", file=asset["file"], received=received, bytes=asset.get("bytes"))
            if digest(part) != asset["sha256"]:
                part.unlink(missing_ok=True)
                raise RuntimeError("download failed sha256 validation")
            part.replace(target)
            progress("asset-ready", file=asset["file"], source="download", bytes=asset.get("bytes"))
            return target
        except (OSError, urllib.error.URLError, RuntimeError) as error:
            if attempt == attempts:
                raise RuntimeError("Could not load %s after %d attempts: %s" % (asset["file"], attempts, error)) from error
            time.sleep(min(2 ** (attempt - 1), 4))

def validate_envelope(job):
    limits = job["envelope"]
    atoms = len(job["structure"]["atoms"])
    if atoms > limits["maxAtoms"]:
        raise RuntimeError("PLAN_ESCALATION_REQUIRED: maxAtoms")

def json_bytes(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()

def add_bytes(archive, path, content):
    info = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, content)

def main():
    parser = argparse.ArgumentParser(description="Run a Tako calculation in Code Interpreter")
    parser.add_argument("job", nargs="?", default="job.json")
    parser.add_argument("--manifest", default="runtime-manifest.json")
    parser.add_argument("--cache", default=".tako-cache")
    parser.add_argument("--output", default="result.tako.zip")
    options = parser.parse_args()
    package_dir = Path(options.job).resolve().parent
    job = json.loads(Path(options.job).read_text())
    manifest = json.loads(Path(options.manifest).read_text())
    if job.get("schemaVersion") != "tako-job-v1" or manifest.get("schemaVersion") != "tako-ci-runtime-v1":
        raise RuntimeError("Unsupported Tako job or runtime schema")
    validate_envelope(job)
    cache = Path(options.cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    for asset in manifest["assets"]:
        download(asset, cache, package_dir)
    host = shutil.which("node") or shutil.which("bun")
    if not host:
        raise RuntimeError("A Node-compatible WebAssembly host is required")
    raw_result = package_dir / "result.json"
    runner = package_dir / "run.mjs"
    if not runner.is_file():
        runner = Path(__file__).resolve().parent / "run.mjs"
    command = [host, str(runner), "--job", str(Path(options.job).resolve()), "--manifest", str(Path(options.manifest).resolve()), "--asset-dir", str(cache), "--output", str(raw_result)]
    subprocess.run(command, check=True)
    result = json.loads(raw_result.read_text())
    provenance = {"jobSchema": job["schemaVersion"], "runtimeSchema": manifest["schemaVersion"], "runtimeAssets": [{"file": a["file"], "sha256": a["sha256"]} for a in manifest["assets"]], "assessment": job["assessment"], "outputPlan": job["outputPlan"]}
    presentation = {"activeView": "structure", "operation": job["operation"]}
    payloads = {
        "result.json": ("result", json_bytes(result)),
        "provenance.json": ("provenance", json_bytes(provenance)),
        "presentation.json": ("presentation", json_bytes(presentation)),
    }
    manifest_entries = [{"path": path, "kind": kind, "bytes": len(content)} for path, (kind, content) in payloads.items()]
    with zipfile.ZipFile(options.output, "w") as archive:
        for path, (_, content) in payloads.items():
            add_bytes(archive, path, content)
        add_bytes(archive, "manifest.json", json_bytes({"schemaVersion": "tako-result-bundle-v1", "entries": manifest_entries}))
    progress("complete", output=str(Path(options.output).resolve()))

if __name__ == "__main__":
    main()
