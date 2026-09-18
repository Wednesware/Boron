import json
import urllib
from pathlib import Path
import zipfile

import pytest

import boron
from boron.lookup import Information, lookup


def test_download_release_uses_default_branch_head(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout=30):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "/releases/latest" in url:
            raise AssertionError("release endpoint should not be used")
        if url == "https://api.github.com/repos/CoolDev/b_GamingInformation":
            return FakeResponse({"default_branch": "main"})
        raise AssertionError(f"Unexpected URL: {url}")

    class FakeZipFile:
        def __init__(self, archive_path):
            self.archive_path = archive_path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extractall(self, destination):
            (destination / "b_GamingInformation-main").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(boron.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(boron.urllib.request, "urlretrieve", lambda url, path: Path(path).write_bytes(b"zip"))
    monkeypatch.setattr(boron.zipfile, "ZipFile", FakeZipFile)

    extracted = boron.download_release("CoolDev", "b_GamingInformation", cache_dir=cache_dir)

    assert extracted == cache_dir / "b_GamingInformation-main"


def test_parse_identifier_examples():
    assert boron.parse_identifier("CoolDev's Gaming Information") == ("CoolDev", "b_GamingInformation")
    assert boron.parse_identifier("Johnathan John's PLAQUE INFO") == ("JohnathanJohn", "b_plaqueinfo")
    assert boron.parse_identifier("ashley myers' movies") == ("AshleyMyers", "b_movies")


def test_lookup_builds_information_tree(monkeypatch, tmp_path):
    root = tmp_path / "release"
    (root / "docs").mkdir(parents=True)
    (root / "src").mkdir(parents=True)
    (root / "_private").mkdir()
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    (root / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "_private" / "secret.txt").write_text("hidden\n", encoding="utf-8")

    def fake_download(owner: str, repo: str, cache_dir: Path):
        return root

    monkeypatch.setattr(boron.lookup, "download_release", fake_download)

    info = lookup("CoolDev's Gaming Information", cache_dir=tmp_path / "cache")

    assert isinstance(info, Information)
    assert info.name == "b_GamingInformation"
    assert "README.md" in info.children
    assert "docs" in info.children
    assert "_private" not in info.children
    assert info.children["src"].children["main.py"].content == "print('hi')\n"


def test_lookup_uses_cache_only_for_offline_or_rate_limit_errors(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    info = boron.Information(name="b_GamingInformation", kind="directory")
    info.children["README.md"] = boron.Information(name="README.md", kind="file", content="cached\n")
    (cache_dir / "lookups.json").write_text(
        json.dumps([
            {
                "owner": "CoolDev",
                "repo": "b_GamingInformation",
                "identifier": "CoolDev's Gaming Information",
                "tree": info.to_dict(),
            }
        ]),
        encoding="utf-8",
    )

    def fake_download(*args, **kwargs):
        raise RuntimeError("Repository does not exist.")

    monkeypatch.setattr(boron, "download_release", fake_download)

    with pytest.raises(RuntimeError, match="does not exist|Nonexistent lookup"):
        lookup("CoolDev's Gaming Information", cache_dir=cache_dir)


def test_information_can_resolve_nested_file_contents(tmp_path):
    root = tmp_path / "boron-info"
    root.mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
    (root / "README.md").write_text("hello\n", encoding="utf-8")

    info = boron.Information.from_directory(root)

    assert info["README.md"].content == "hello\n"
    assert info["docs/guide.md"].content == "guide\n"
    assert info.get_file("docs/guide.md") == "guide\n"
    assert info.children["docs"].get_file("guide.md") == "guide\n"


def test_lookup_uses_cached_history_when_offline(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    info = boron.Information(name="b_GamingInformation", kind="directory")
    info.children["README.md"] = boron.Information(name="README.md", kind="file", content="cached\n")
    (cache_dir / "lookups.json").write_text(
        json.dumps([
            {
                "owner": "CoolDev",
                "repo": "b_GamingInformation",
                "identifier": "CoolDev's Gaming Information",
                "tree": info.to_dict(),
            }
        ]),
        encoding="utf-8",
    )

    def fake_download(*args, **kwargs):
        raise RuntimeError("You are offline.")

    monkeypatch.setattr(boron, "download_release", fake_download)

    result = lookup("CoolDev's Gaming Information", cache_dir=cache_dir, offline=True)

    assert result.get_file("README.md") == "cached\n"


def test_lookup_shell_uses_child_items(monkeypatch, capsys):
    info = boron.Information(name="b_information")
    readme = boron.Information(name="README.md", kind="file", content="# Title\nHello")
    docs = boron.Information(name="docs", kind="directory")
    docs.children["guide.md"] = boron.Information(name="guide.md", kind="file", content="Guide")
    info.children["README.md"] = readme
    info.children["docs"] = docs

    class FakeSelectMenu:
        def __init__(self, options, title):
            self.options = options
            self.title = title

    class FakeKeymap:
        def __init__(self):
            pass

        def on(self, *_args, **_kwargs):
            def decorator(func):
                return func
            return decorator

    class FakeColor:
        gray = ""
        reset = ""

    class FakeIodineModule:
        Keymap = FakeKeymap
        @staticmethod
        def run(menu, **kwargs):
            return "selected"

    def fake_require(name):
        if name == "iodine":
            return FakeIodineModule()
        if name == "iodine.widgets.select":
            return type("SelectModule", (), {"SelectMenu": FakeSelectMenu})()
        if name == "magnesium.color":
            return type("ColorModule", (), {"Color": FakeColor})()
        raise AssertionError(name)

    monkeypatch.setattr(boron, "require", fake_require, raising=False)
    monkeypatch.setattr(boron, "lookup", lambda identifier: info)

    result = boron.lookup_shell("jscrml's information")

    assert result == info
    captured = capsys.readouterr()
    assert "Lookup complete." in captured.out


def test_source_deduplicates_repositories(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    entries = [
        {"owner": "CoolDev", "repo": "b_GamingInformation", "identifier": "CoolDev's Gaming Information"},
        {"owner": "CoolDev", "repo": "b_GamingInformation", "identifier": "CoolDev's Gaming Information"},
        {"owner": "JohnathanJohn", "repo": "b_plaqueinfo", "identifier": "Johnathan John's PLAQUE INFO"},
    ]
    (cache_dir / "lookups.json").write_text(json.dumps(entries), encoding="utf-8")

    generated = boron.source(force=True, cache_dir=cache_dir, source_file=tmp_path / "SOURCE.md")

    assert generated.count("- [CoolDev/b_GamingInformation](https://github.com/CoolDev/b_GamingInformation)") == 1
    assert generated.count("- [JohnathanJohn/b_plaqueinfo](https://github.com/JohnathanJohn/b_plaqueinfo)") == 1


def test_save_and_list_bookmarks_round_trip(tmp_path):
    bookmark_dir = tmp_path / "bookmarks"
    path = boron.save_bookmark("# Example\nHello", "CoolDev", "b_GamingInformation", "README.md", bookmarks_dir=bookmark_dir)

    assert path.parent == bookmark_dir
    assert path.name.endswith(".bbm")

    bookmarks = boron.list_bookmarks(bookmark_dir)
    assert len(bookmarks) == 1
    assert bookmarks[0]["author"] == "CoolDev"
    assert bookmarks[0]["source"] == "b_GamingInformation"
    assert bookmarks[0]["name"] == "README.md"
    assert bookmarks[0]["content"] == "# Example\nHello"
    assert bookmarks[0]["label"] == "README.md from CoolDev's b_GamingInformation"


def test_lookup_bookmarks_are_loaded_as_information_trees(tmp_path):
    bookmark_dir = tmp_path / "bookmarks"
    info = boron.Information(name="b_GamingInformation", kind="directory")
    info.children["README.md"] = boron.Information(name="README.md", kind="file", content="# Title\nHello")

    path = boron.save_lookup_bookmark(info, "CoolDev", "b_GamingInformation", bookmarks_dir=bookmark_dir)
    loaded = boron.load_bookmark(path)

    assert isinstance(loaded, boron.Information)
    assert loaded.name == "b_GamingInformation"
    assert loaded["README.md"].content == "# Title\nHello"
