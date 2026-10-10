"""Tarball snapshot safety, search_repo, and tarball download caps. No network."""
import asyncio
import io
import tarfile

import httpx
import pytest

from app.agent.tools import RepoToolbox
from app.steps import StepLog
from app.tools.github import GitHubClient, GitHubError, RepoRef
from app.tools.search import RepoSnapshot, format_matches, safe_member_path


def make_tarball(entries) -> bytes:
    """entries: list of (name, bytes | ('symlink', target) | ('hardlink', target))."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in entries:
            info = tarfile.TarInfo(name)
            if isinstance(content, tuple):
                info.type = tarfile.SYMTYPE if content[0] == "symlink" else tarfile.LNKTYPE
                info.linkname = content[1]
                tf.addfile(info)
            else:
                info.size = len(content)
                tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


ROOT = "acme-demo-abc123/"
GOOD = [
    (ROOT + "README.md", b"# Demo\nWe use neatlogs and retry on failure.\n"),
    (ROOT + "src/agent.py", b"import neatlogs\n\ndef run():\n    neatlogs.init()\n    for attempt in range(3):\n        pass  # retry\n"),
    (ROOT + "docs/guide.md", b"neatlogs is great\n"),
    (ROOT + "tests/test_agent.py", b"import neatlogs\n"),
]


def snap(extra=()):
    return RepoSnapshot.from_tarball(make_tarball(GOOD + list(extra)))


def test_snapshot_keeps_text_and_rejects_unsafe_members():
    s = snap([
        (ROOT + "link_to_passwd", ("symlink", "/etc/passwd")),
        (ROOT + "hard", ("hardlink", ROOT + "src/agent.py")),
        (ROOT + "../../escape.py", b"evil"),
        (ROOT + "web/node_modules/lib/index.js", b"neatlogs"),
        (ROOT + "package-lock.json", b"{}"),
        (ROOT + "logo.png", b"\x89PNG"),
        (ROOT + "data.bin.txt", b"abc\x00def"),
        (ROOT + "huge.py", b"x" * (600 * 1024)),
    ])
    assert set(s.files) == {"README.md", "src/agent.py", "docs/guide.md", "tests/test_agent.py"}
    assert s.skipped["symlink"] == 2
    assert s.skipped["unsafe_path"] == 1
    assert s.skipped["vendored_or_build"] == 1
    assert s.skipped["lockfile"] == 1
    assert s.skipped["binary"] == 2
    assert s.skipped["too_large"] == 1


@pytest.mark.parametrize("name,ok", [
    ("r-abc/src/a.py", "src/a.py"), ("r-abc/../x", None), ("/abs/path", None),
    ("r-abc/a\\b.py", None), ("r-abc/a\x00.py", None), ("r-abc", None), ("r-abc/./a.py", "a.py"),
])
def test_safe_member_path(name, ok):
    assert safe_member_path(name) == ok


def test_garbage_tarball_raises():
    with pytest.raises(ValueError):
        RepoSnapshot.from_tarball(b"not a tarball")


def test_search_ranks_code_before_docs_and_readme_last():
    matches, total, files = snap().search("NEATLOGS")
    order = [m["path"] for m in matches]
    assert order[0] == "src/agent.py" and order[-1] == "README.md"
    assert order == ["src/agent.py", "src/agent.py", "tests/test_agent.py", "docs/guide.md", "README.md"]
    assert total == 5 and "README.md" in files


def test_search_alternatives_context_and_format():
    matches, total, files = snap().search("retry|neatlogs.init")
    agent_hits = [m for m in matches if m["path"] == "src/agent.py"]
    assert [m["line"] for m in agent_hits] == [4]  # line 6 merged into line 4's context
    assert "4: " in agent_hits[0]["snippet"] and "6- " in agent_hits[0]["snippet"]
    assert total == 3  # README.md also says "retry"
    out = format_matches("retry", matches, total, files)
    assert "== src/agent.py:4" in out


def test_search_treats_regex_metacharacters_literally():
    s = snap([(ROOT + "re.py", b"x = (a+)+$\n")])
    matches, *_ = s.search("(a+)+$")
    assert matches and matches[0]["path"] == "re.py"
    with pytest.raises(ValueError):
        s.search(" | x ")


def test_search_repo_tool_and_grounding_paths():
    box = RepoToolbox(None, None, "main", [], [], StepLog(), snapshot=snap())
    out = asyncio.run(box.dispatch("search_repo", '{"pattern": "neatlogs.init"}'))
    assert "src/agent.py:4" in out and out.startswith("<<<UNTRUSTED_DATA")
    assert "src/agent.py" in box.searched_paths
    page = asyncio.run(box.dispatch("read_file", '{"path": "src/agent.py", "start_line": 4}'))
    assert "4:     neatlogs.init()" in page and "1: import" not in page


def test_search_repo_without_snapshot_explains_fallback():
    box = RepoToolbox(None, None, "main", ["a.py"], [], StepLog())
    out = asyncio.run(box.dispatch("search_repo", '{"pattern": "x"}'))
    assert out.startswith("ERROR") and "tarball" in out


def _client(handler):
    return GitHubClient(token="", transport=httpx.MockTransport(handler))


def test_tarball_download_respects_declared_size_cap():
    def handler(req):
        return httpx.Response(200, headers={"content-length": str(50 * 2**20)}, content=b"x")

    async def go():
        async with _client(handler) as gh:
            await gh.download_tarball(RepoRef("acme", "demo"), "main")

    with pytest.raises(GitHubError) as e:
        asyncio.run(go())
    assert e.value.kind == "too_large"


def test_tarball_download_respects_streamed_size_cap():
    def handler(req):
        return httpx.Response(200, content=b"x" * 5000)  # no trustworthy length

    async def go():
        async with _client(handler) as gh:
            return await gh.download_tarball(RepoRef("acme", "demo"), "main", max_bytes=1000)

    with pytest.raises(GitHubError):
        asyncio.run(go())


def test_tarball_download_ok():
    data = make_tarball(GOOD)

    def handler(req):
        assert req.url.path == "/repos/acme/demo/tarball/main"
        return httpx.Response(200, content=data)

    async def go():
        async with _client(handler) as gh:
            return await gh.download_tarball(RepoRef("acme", "demo"), "main")

    assert RepoSnapshot.from_tarball(asyncio.run(go())).files["src/agent.py"].startswith("import neatlogs")
