"""Read-only, in-memory copy of a repo (from its tarball) and search_repo over it.

Nothing is written to disk and nothing is executed. The tarball is UNTRUSTED:
symlinks/hardlinks, absolute paths, '..' and odd characters are rejected; binaries,
vendored dirs and lockfiles are skipped; per-file, total and uncompressed caps stop
decompression bombs.
"""
import io
import posixpath
import tarfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

MAX_FILE_BYTES = 512 * 1024
MAX_TEXT_BYTES = 40 * 1024 * 1024        # kept in memory
MAX_UNCOMPRESSED = 600 * 1024 * 1024     # walked through, including skipped members
MAX_FILES = 20_000

SKIP_DIRS = {
    "node_modules", "vendor", "vendors", "third_party", ".git", "dist", "build", "out",
    "__pycache__", ".venv", "venv", "env", "site-packages", ".next", ".nuxt", "target",
    "bower_components", ".tox", ".mypy_cache", ".pytest_cache", "coverage", ".gradle",
}
LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock",
    "Cargo.lock", "composer.lock", "Gemfile.lock", "go.sum", "uv.lock", "bun.lockb",
    "npm-shrinkwrap.json", "pdm.lock",
}
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff", ".svg", ".pdf",
    ".zip", ".gz", ".tgz", ".tar", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war", ".class",
    ".so", ".dylib", ".dll", ".exe", ".bin", ".o", ".a", ".pyc", ".whl", ".egg",
    ".mp4", ".mov", ".avi", ".webm", ".mp3", ".wav", ".ogg", ".flac", ".m4a",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".psd", ".sketch", ".fig",
    ".sqlite", ".db", ".parquet", ".npy", ".npz", ".pkl", ".pickle", ".pt", ".pth",
    ".onnx", ".h5", ".ckpt", ".safetensors", ".min.js", ".map",
}
DOC_EXT = {".md", ".rst", ".txt", ".adoc"}

SEARCH_MAX_MATCHES = 12
SEARCH_CONTEXT = 2
SEARCH_MAX_CHARS = 3500
LINE_CHARS = 200


def safe_member_path(name: str) -> str | None:
    """Strip GitHub's 'owner-repo-sha/' prefix; None if the path is unsafe."""
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        return None
    parts = name.split("/")
    if ".." in parts:
        return None
    rest = "/".join(parts[1:])                      # drop the top-level directory
    if not rest:
        return None
    norm = posixpath.normpath(rest)
    if norm.startswith("..") or norm.startswith("/") or norm == ".":
        return None
    return norm


def _skip_reason(path: str, size: int) -> str | None:
    p = PurePosixPath(path)
    if any(part in SKIP_DIRS for part in p.parts[:-1]):
        return "vendored_or_build"
    if p.name in LOCKFILES:
        return "lockfile"
    low = p.name.lower()
    if any(low.endswith(ext) for ext in BINARY_EXT):
        return "binary"
    if size > MAX_FILE_BYTES:
        return "too_large"
    return None


@dataclass
class RepoSnapshot:
    files: dict[str, str] = field(default_factory=dict)
    skipped: Counter = field(default_factory=Counter)
    text_bytes: int = 0
    truncated: bool = False

    @classmethod
    def from_tarball(cls, data: bytes) -> "RepoSnapshot":
        snap = cls()
        walked = 0
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
                for m in tf:
                    walked += max(m.size, 0)
                    if walked > MAX_UNCOMPRESSED or len(snap.files) >= MAX_FILES:
                        snap.truncated = True
                        break
                    if m.issym() or m.islnk():
                        snap.skipped["symlink"] += 1
                        continue
                    if not m.isfile():
                        if not m.isdir():
                            snap.skipped["special"] += 1
                        continue
                    path = safe_member_path(m.name)
                    if path is None:
                        snap.skipped["unsafe_path"] += 1
                        continue
                    reason = _skip_reason(path, m.size)
                    if reason:
                        snap.skipped[reason] += 1
                        continue
                    f = tf.extractfile(m)
                    raw = f.read(MAX_FILE_BYTES + 1) if f else b""
                    if b"\x00" in raw[:8192]:
                        snap.skipped["binary"] += 1
                        continue
                    if snap.text_bytes + len(raw) > MAX_TEXT_BYTES:
                        snap.truncated = True
                        break
                    snap.files[path] = raw.decode("utf-8", errors="replace")
                    snap.text_bytes += len(raw)
        except (tarfile.TarError, EOFError, OSError) as exc:
            if not snap.files:
                raise ValueError(f"unreadable tarball: {type(exc).__name__}") from exc
            snap.truncated = True  # keep what we read before the corruption
        return snap

    def summary(self) -> dict:
        return {"files": len(self.files), "text_mb": round(self.text_bytes / 2**20, 2),
                "skipped": dict(self.skipped), "truncated": self.truncated}

    def search(self, pattern: str, max_matches: int = SEARCH_MAX_MATCHES,
               context: int = SEARCH_CONTEXT) -> tuple[list[dict], int, set[str]]:
        """Case-insensitive literal search; '|' separates alternatives.

        Code files are searched before docs, and the README last (it can't prove itself).
        Returns (matches, total_hits, files_with_hits).
        """
        terms = [t.strip().lower() for t in pattern.split("|") if len(t.strip()) >= 2][:6]
        if not terms:
            raise ValueError("pattern needs at least one term of 2+ characters")
        matches, total, hit_files = [], 0, set()
        for path in sorted(self.files, key=_search_rank):
            lines = self.files[path].splitlines()
            last_shown = -10**9
            for i, line in enumerate(lines):
                low = line.lower()
                if not any(t in low for t in terms):
                    continue
                total += 1
                hit_files.add(path)
                if i - last_shown <= context:
                    continue  # already visible in the previous snippet's context
                if len(matches) < max_matches:
                    last_shown = i
                    lo, hi = max(0, i - context), min(len(lines), i + context + 1)
                    snippet = [f"{n + 1}{':' if n == i else '-'} {lines[n][:LINE_CHARS]}" for n in range(lo, hi)]
                    matches.append({"path": path, "line": i + 1, "snippet": "\n".join(snippet)})
        return matches, total, hit_files


def _search_rank(path: str) -> tuple:
    p = PurePosixPath(path)
    is_readme = p.name.lower().startswith("readme") and len(p.parts) == 1
    is_doc = p.suffix.lower() in DOC_EXT or "docs" in p.parts
    is_test = any(part in ("tests", "test") for part in p.parts) or p.name.startswith("test_")
    is_dotfile = any(part.startswith(".") for part in p.parts)  # .gitignore, .github/...
    return (is_readme, is_doc, is_dotfile, is_test, path.count("/"), path)


def format_matches(pattern: str, matches: list[dict], total: int, hit_files: set[str]) -> str:
    if not matches:
        return f"no matches for {pattern!r}"
    out, size = [], 0
    for m in matches:
        block = f"== {m['path']}:{m['line']}\n{m['snippet']}"
        if size + len(block) > SEARCH_MAX_CHARS:
            break
        out.append(block)
        size += len(block)
    more = total - len(out)
    tail = f"\n... {more} more matching lines across {len(hit_files)} files" if more > 0 else ""
    return "\n".join(out) + tail
