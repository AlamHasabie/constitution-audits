"""Shared record plumbing: ids, result-file discovery, provenance, resume.

Used by the scripts that read one stage's output and write another's
(run_rescore.py, run_rater.py). The search loop writes its own records through
JSONStreamer and does not use this.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Fold case and whitespace, for identity comparisons."""
    return _WS.sub(" ", (text or "").strip().lower())


def prompt_id(query: str) -> str:
    """Stable id for a prompt, so records join across stages."""
    return hashlib.sha256(normalize_text(query).encode("utf-8")).hexdigest()[:16]


def pair_id(query: str, response: str) -> str:
    """
    Stable id for a (query, response) pair.

    Rating the same pair repeatedly is the whole point of an agreement pass, so
    the pair needs an identity that does not depend on which file it came from
    or what score it was given.
    """
    joined = normalize_text(query) + "\x00" + normalize_text(response)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def iter_results_files(source: Path) -> Iterator[Path]:
    """
    Yield results.jsonl files under a run dir, a sweep dir, or a direct path.

    The patterns overlap, so each resolved path is yielded at most once -- reading
    one file twice would double-count whatever the caller is counting.
    """
    if source.is_file():
        yield source
        return
    if not source.is_dir():
        raise FileNotFoundError(f"no such path: {source}")

    seen: set = set()

    # Sweep layout is <dir>/runs/run_*/results.jsonl; run_persona.py writes
    # <dir>/run_*/results.jsonl. The last pattern catches any other one-level
    # layout.
    candidates = [source / "results.jsonl"]
    for pattern in ("runs/*/results.jsonl", "run_*/results.jsonl", "*/results.jsonl"):
        candidates.extend(sorted(source.glob(pattern)))

    for path in candidates:
        if not path.exists():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield path


def origin_label(path: Path) -> str:
    """
    Label saying which search produced a pooled record.

    Built from the results file's position under the nearest enclosing
    "results" directory, so `phaseA_flash/run_1` and `phaseA_tulu/run_1` stay
    distinct. The obvious shorthand -- the source argument's name plus the
    file's parent name -- collapses exactly the case that matters: --from
    results/phaseA_flash/run_1 and --from results/phaseA_tulu/run_1 both reduce
    to "run_1/run_1", and a pooled record then cannot say where it came from.
    Every record in results/agreement_1 carries that collapsed value.

    Origin is the stratifying variable for any cross-target or cross-rater
    comparison, since a prompt found by searching against one target is not
    neutral between targets. A label that cannot separate the sources silently
    turns that stratum into a single bucket.
    """
    directory = path.parent.resolve()
    parts = directory.parts

    for i in range(len(parts) - 1, -1, -1):
        if parts[i].lower() == "results":
            below = parts[i + 1:]
            if below:
                return "/".join(below)
            break

    # No "results" ancestor: the last two components at least keep sibling run
    # directories apart, which the single-name form does not.
    return "/".join(parts[-2:]) if len(parts) >= 2 else directory.name


def read_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    """Yield parseable objects from a JSONL file, skipping malformed lines."""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_provenance(repo_root: Path) -> Dict[str, Any]:
    """
    Current commit and whether the tree is dirty.

    The dirty flag matters: a bare commit sha taken from a modified tree
    describes code that is not the code that ran.
    """

    def run(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(
                args, cwd=repo_root, capture_output=True, text=True, timeout=10
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    status = run("git", "status", "--porcelain")
    return {
        "git_commit": run("git", "rev-parse", "HEAD"),
        "git_dirty": bool(status) if status is not None else None,
    }


def load_done_keys(path: Path, fields: Sequence[str]) -> set:
    """
    Keys already present in a records file, for resume.

    A key is the tuple of `fields` from a record; records missing any field are
    ignored rather than counted as done.
    """
    done: set = set()
    if not path.exists():
        return done
    for entry in read_jsonl(path):
        key = tuple(entry.get(f) for f in fields)
        if all(k is not None for k in key):
            done.add(key)
    return done


def parse_labelled(raw: List[str], what: str) -> Dict[str, str]:
    """Parse repeated LABEL=VALUE arguments into {label: value}."""
    out: Dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"--{what} must be LABEL=VALUE, got {item!r}")
        label, value = item.split("=", 1)
        label, value = label.strip(), value.strip()
        if not label or not value:
            raise ValueError(f"--{what} must be LABEL=VALUE, got {item!r}")
        if label in out:
            raise ValueError(f"duplicate --{what} label {label!r}")
        out[label] = value
    return out
