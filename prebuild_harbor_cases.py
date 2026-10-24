#!/usr/bin/env python3
"""Pre-build Harbor Dockerfile tasks and optionally pin local images in task.toml.

Requires Python >=3.11 and Docker CLI.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import threading
import tomllib
from pathlib import Path

PRINT_LOCK = threading.Lock()


def say(msg: str) -> None:
    with PRINT_LOCK:
        print(msg, flush=True)


def tasks_at(path: Path) -> list[Path]:
    if (path / "task.toml").is_file():
        return [path]
    return sorted(p for p in path.iterdir()
                  if p.is_dir() and (p / "task.toml").is_file())


def context_hash(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_symlink():
            raise ValueError(f"Symlink unsupported in build context: {p}")
        if not p.is_file():
            continue
        rel = p.relative_to(path).as_posix()
        if rel.startswith(".git/") or rel.startswith("__pycache__/"):
            continue
        h.update(rel.encode() + b"\x00")
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        h.update(b"\x00")
    return h.hexdigest()[:16]


def image_name(prefix: str, task: Path) -> str:
    slug = re.sub(r"[^a-z0-9_.-]", "-", task.name.lower()).strip("-.")
    if not slug:
        raise ValueError(f"Invalid task name: {task.name}")
    return f"{prefix}/{slug}:{context_hash(task / 'environment')}"


def pin_image(task: Path, image: str, replace_existing: bool) -> None:
    path = task / "task.toml"
    original = path.read_text(encoding="utf-8")
    doc = tomllib.loads(original)
    env = doc.get("environment")
    if not isinstance(env, dict):
        raise ValueError(f"{path} has no [environment] table")
    previous = env.get("docker_image")
    if previous == image:
        return
    if previous and not replace_existing:
        raise ValueError(f"Existing docker_image={previous!r}; pass --replace-existing to override")

    sec = re.search(r"(?m)^\[environment\][ \t]*(?:#.*)?$", original)
    if sec is None:
        raise ValueError(f"Can't find plain [environment] in {path}")
    end_match = re.search(r"(?m)^\[", original[sec.end():])
    end = sec.end() + end_match.start() if end_match else len(original)
    head, block, tail = original[:sec.end()], original[sec.end():end], original[end:]
    line = f'docker_image = "{image}"'
    if previous:
        block, n = re.subn(r"(?m)^[ \t]*docker_image[ \t]*=.*$", line, block, count=1)
        if n != 1:
            raise ValueError(f"Could not replace existing docker_image in {path}")
    else:
        block = block.rstrip("\n") + "\n" + line + "\n\n"
    updated = head + block + tail
    if tomllib.loads(updated)["environment"].get("docker_image") != image:
        raise ValueError("Generated task.toml failed validation")

    fd, tmpname = tempfile.mkstemp(prefix=".task-prebuild-", dir=task)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(updated)
        os.chmod(tmpname, path.stat().st_mode & 0o777)
        os.replace(tmpname, path)
    finally:
        if os.path.exists(tmpname):
            os.unlink(tmpname)


def build_one(task: Path, args: argparse.Namespace, logs: Path) -> tuple[str, str]:
    dockerfile = task / "environment" / "Dockerfile"
    if not dockerfile.is_file():
        return "skip", f"{task.name}: no environment/Dockerfile"
    try:
        image = image_name(args.image_prefix, task)
        if not args.rebuild:
            probe = subprocess.run(["docker", "image", "inspect", image],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            exists = probe.returncode == 0
        else:
            exists = False
        if not exists:
            # Do not pass --progress: legacy builder rejects it, and BuildKit
            # already defaults to plain output when stdout is redirected to a file.
            cmd = ["docker", "build", "-t", image]
            if args.network != "default":
                cmd += ["--network", args.network]
            if args.proxy:
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                    cmd += ["--build-arg", f"{key}={args.proxy}"]
                if args.no_proxy:
                    for key in ("NO_PROXY", "no_proxy"):
                        cmd += ["--build-arg", f"{key}={args.no_proxy}"]
            cmd += [str(dockerfile.parent)]
            if args.dry_run:
                return "dry", f"{task.name}: would build {image}"
            logfile = logs / f"{task.name}.log"
            say(f"[BUILD] {task.name} -> {image} (log: {logfile})")
            with logfile.open("w", encoding="utf-8") as out:
                rc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT).returncode
            if rc:
                return "failed", f"{task.name}: docker build exit={rc}; see {logfile}"
        else:
            say(f"[CACHED] {task.name}: {image}")
        if args.dry_run:
            return "dry", f"{task.name}: would pin {image}"
        if not args.no_pin:
            pin_image(task, image, args.replace_existing)
        return "ok", f"{task.name}: {image}" + (" (pinned)" if not args.no_pin else "")
    except Exception as e:
        return "failed", f"{task.name}: {type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path, help="dataset directory or one Harbor task directory")
    ap.add_argument("--proxy", default="", help="HTTP proxy address, e.g. http://127.0.0.1:7890")
    ap.add_argument("--no-proxy", default="localhost,127.0.0.1", help="NO_PROXY build argument")
    ap.add_argument("--network", choices=("default", "host"), default=None,
                    help="Docker build RUN network (auto=host if proxy contains localhost)")
    ap.add_argument("--jobs", type=int, default=2, help="concurrent builds (default 2)")
    ap.add_argument("--limit", type=int, default=0, help="limit to first N tasks")
    ap.add_argument("--image-prefix", default="harbor-local", help="local Docker repository prefix")
    ap.add_argument("--rebuild", action="store_true", help="force build even if tagged image exists")
    ap.add_argument("--no-pin", action="store_true", help="only build; do not modify task.toml")
    ap.add_argument("--replace-existing", action="store_true", help="overwrite existing docker_image field")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.jobs < 1 or args.limit < 0:
        ap.error("--jobs must be >=1 and --limit must be >=0")
    args.root = args.root.resolve()
    if not args.root.is_dir():
        ap.error(f"not a directory: {args.root}")
    tasks = tasks_at(args.root)
    if args.limit:
        tasks = tasks[:args.limit]
    if not tasks:
        ap.error("no task.toml files found directly under this directory")
    if args.network is None:
        args.network = "host" if args.proxy and re.search(r"(?:localhost|127\.0\.0\.1|\[::1\])", args.proxy) else "default"
    if args.proxy and args.network == "default" and re.search(r"(?:localhost|127\.0\.0\.1|\[::1\])", args.proxy):
        say("[WARN] localhost proxy usually requires --network host on Linux")
    logs = (args.root.parent if (args.root / "task.toml").exists() else args.root) / ".prebuild-logs"
    if not args.dry_run:
        logs.mkdir(exist_ok=True)
    say(f"Tasks: {len(tasks)} | jobs: {args.jobs} | proxy: {'configured' if args.proxy else 'none'} | build network: {args.network}")
    outcomes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futures = [ex.submit(build_one, task, args, logs) for task in tasks]
        for fut in concurrent.futures.as_completed(futures):
            status, message = fut.result()
            say(f"[{status.upper()}] {message}")
            outcomes.append(status)
    say(f"SUMMARY: ok={outcomes.count('ok')} failed={outcomes.count('failed')} skipped={outcomes.count('skip')}")
    return 1 if "failed" in outcomes else 0


if __name__ == "__main__":
    sys.exit(main())
