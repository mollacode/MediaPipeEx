#!/usr/bin/env python3
"""Restore a pinned upstream plus a complete, verified local source patch.

Uses only Python's standard library and Git. It never resets an existing source
tree, downloads build inputs, invokes a compiler, or installs an SDK.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import uuid


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], stderr=subprocess.PIPE
    )


def safe_path(root, name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or any(x in ("..", ".git") for x in p.parts)
            or "\\" in name or "\0" in name):
        raise ValueError("unsafe source path")
    target = root.joinpath(*p.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("source path escapes its root")
    return target


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_state(root, version):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", version):
        raise ValueError("expected a numeric SDK version")
    manifest = safe_path(root, version + "/source-state/manifest.json")
    state = json.loads(manifest.read_text())
    if state.get("schema") != 1 or state.get("version") != version:
        raise ValueError("source manifest schema/version mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", state["upstreamCommit"]):
        raise ValueError("invalid upstream commit")
    patch = safe_path(root, state["patchFile"]).read_bytes()
    if sha(patch) != state["patchSha256"]:
        raise ValueError("source patch checksum mismatch")
    for name, entry in state["files"].items():
        safe_path(root, name)
        if entry["mode"] not in (0o644, 0o755):
            raise ValueError("unsupported source file mode")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("invalid source checksum")
        snapshot = safe_path(root, state["reviewSources"][name])
        if sha(snapshot.read_bytes()) != entry["sha256"]:
            raise ValueError("review source checksum mismatch")
    for name in state["generatedInputs"]:
        safe_path(root, name)
    for name in state["trackedChanges"] + state["intentToAdd"]:
        safe_path(root, name)
    extras = {}
    for name, source in state["extraSources"].items():
        safe_path(root, name)
        content = safe_path(root, source).read_bytes()
        if name not in state["files"] or sha(content) != state["files"][name]["sha256"]:
            raise ValueError("extra source checksum mismatch")
        extras[name] = content
    return state, patch, extras


def verify_tree(tree, state):
    if git(tree, "rev-parse", "--show-toplevel").decode().strip() != str(tree.resolve()):
        raise ValueError("source is not its own Git worktree")
    if git(tree, "rev-parse", "HEAD").decode().strip() != state["upstreamCommit"]:
        raise ValueError("source upstream commit mismatch")
    for name, entry in state["files"].items():
        p = safe_path(tree, name)
        if p.is_symlink() or not p.is_file() or sha(p.read_bytes()) != entry["sha256"]:
            raise ValueError("source file checksum mismatch: " + name)
        if stat.S_IMODE(p.stat().st_mode) != entry["mode"]:
            raise ValueError("source file mode mismatch: " + name)
    changed = set(git(tree, "diff", "--name-only", "HEAD", "-z").decode().rstrip("\0").split("\0")) - {""}
    # New files produced by git apply are untracked until intent-to-add below.
    if changed != set(state["trackedChanges"]):
        raise ValueError("unexpected tracked source changes")
    untracked = set(git(tree, "ls-files", "--others", "--exclude-standard", "-z").decode().rstrip("\0").split("\0")) - {""}
    if untracked - set(state["extraSources"]) - set(state["generatedInputs"]):
        raise ValueError("unexpected untracked source files")


def prepare(root, version, verify_only=False):
    root = root.resolve(strict=True)
    state, patch, extras = load_state(root, version)
    parent = root / version / "source"
    upstream = parent / "upstream"
    target = parent / "findwig"
    if parent.is_symlink() or upstream.is_symlink() or target.is_symlink():
        raise ValueError("source directories must not be symbolic links")
    if git(upstream, "rev-parse", "--show-toplevel").decode().strip() != str(upstream.resolve()):
        raise ValueError("initialize the pinned upstream submodule first")
    if git(upstream, "rev-parse", "HEAD").decode().strip() != state["upstreamCommit"]:
        raise ValueError("upstream submodule commit mismatch")
    if target.exists():
        verify_tree(target, state)
        return "verified-existing"
    if verify_only:
        raise ValueError("modified source worktree has not been prepared")
    staging = parent / (".prepare-" + uuid.uuid4().hex)
    created = False
    try:
        git(upstream, "worktree", "add", "--detach", str(staging), state["upstreamCommit"])
        created = True
        subprocess.run(["git", "-C", str(staging), "apply", "--check", "-"],
                       input=patch, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", str(staging), "apply", "-"],
                       input=patch, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if state["intentToAdd"]:
            git(staging, "add", "-N", "--", *state["intentToAdd"])
        for name, content in extras.items():
            p = safe_path(staging, name)
            if p.exists() or p.is_symlink():
                raise ValueError("extra source would overwrite an existing file")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
            p.chmod(state["files"][name]["mode"])
        verify_tree(staging, state)
        git(upstream, "worktree", "move", str(staging), str(target))
        created = False
        return "prepared"
    finally:
        if created:
            # Only this invocation's newly created, unique staging worktree.
            git(upstream, "worktree", "remove", "--force", str(staging))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="pinned SDK version, e.g. 1.80.0")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        result = prepare(root, args.version, args.verify_only)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, "Source preparation failed: " + str(error).replace(str(root), "${SDK_ROOT}") + "\n")
    print(json.dumps({"version": args.version, "result": result,
                      "generatedBuildInputsIncluded": False}))


if __name__ == "__main__":
    main()
