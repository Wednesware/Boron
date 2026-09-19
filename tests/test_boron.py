import json
import os
import sys
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
    assert boron.parse_identifier("documentation of CoolDev's Gaming Information") == ("CoolDev", "GamingInformation")
    assert boron.parse_identifier("license of CoolDev's Gaming Information") == ("CoolDev", "GamingInformation")


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


def test_ensure_venv_dependencies_installs_required_packages(monkeypatch, tmp_path):
    calls = []
    venv_dir = tmp_path / "venv"

    def fake_ensure_venv(path=None):
        venv_dir.mkdir(parents=True, exist_ok=True)
        return venv_dir

    def fake_python(path):
        return path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def fake_run(args, check=None, stdout=None, **kwargs):
        calls.append(args)
        return 0

    monkeypatch.setattr(boron, "_ensure_venv", fake_ensure_venv)
    monkeypatch.setattr(boron, "_venv_python", fake_python)
    monkeypatch.setattr(boron.subprocess, "run", fake_run)

    python = boron._ensure_venv_dependencies(venv_dir)

    assert python == fake_python(venv_dir)
    assert calls[0][:4] == [str(python), "-m", "pip", "install"]
    assert "wwn" in calls[0]
    assert "pywebview" in calls[0]
    assert "pyperclip" in calls[0]
    assert "PySide6" in calls[0]
    assert "qtpy" in calls[0]


def test_open_page_in_app_prefers_pywebview(monkeypatch, tmp_path):
    called = {}

    class FakeWebView:
        @staticmethod
        def create_window(title, url):
            called["window"] = (title, url)

        @staticmethod
        def start(gui=None):
            called["start"] = gui

    monkeypatch.setitem(sys.modules, "webview", FakeWebView)
    monkeypatch.setattr(boron, "App", None)
    monkeypatch.setattr(boron, "_webview_backend", lambda: "qt")
    monkeypatch.setattr(boron.webbrowser, "open", lambda *args, **kwargs: called.setdefault("browser", True))

    boron._open_page_in_app(str(tmp_path / "index.html"))

    assert called["window"][0] == "Boron"
    assert called["start"] == "qt"
    assert "browser" not in called


def test_main_recovers_nitrogen_before_help(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(boron, "_ensure_boron_dir", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(boron, "_ensure_venv_dependencies", lambda *_args, **_kwargs: tmp_path / "venv" / "bin" / "python")
    monkeypatch.setattr(boron, "_ensure_nitrogen", lambda: True)
    monkeypatch.setattr(boron, "nitrogen_missing", False)
    monkeypatch.setattr(boron.os, "execv", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(boron.Path, "resolve", lambda self: self)

    result = boron.main(["help"])

    assert result == 0
    assert len(calls) == 1


def test_source_this_appends_human_readable_entry_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    info = boron.Information(
        name="README.md",
        kind="file",
        path=str(tmp_path / "lookup" / "README.md"),
        content="# Title\nHello",
    )
    source_info = boron.Information(name="b_GamingInformation", kind="directory")

    boron.source_this(
        info,
        source_info=source_info,
        source_info_author="CoolDev",
        source_info_title="CoolDev's Gaming Information",
    )
    boron.source_this(
        info,
        source_info=source_info,
        source_info_author="CoolDev",
        source_info_title="CoolDev's Gaming Information",
    )

    contents = (tmp_path / "SOURCE.md").read_text(encoding="utf-8")
    assert contents == "- File: README.md | Lookup: CoolDev's Gaming Information | Author: CoolDev\n"


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


def test_grab_folder_copies_directory_tree(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "docs").mkdir()
    (source_root / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
    (source_root / "README.md").write_text("hello\n", encoding="utf-8")

    folder = boron.Information.from_directory(source_root, root_name="source")
    target_root = tmp_path / "grabbed"

    result = boron.grab_folder(folder, target_dir=target_root)

    assert result == target_root / "source"
    assert (result / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert (result / "docs" / "guide.md").read_text(encoding="utf-8") == "guide\n"


def test_information_select_loop_opens_directory_action_shell(monkeypatch):
    folder = boron.Information(name="docs", kind="directory")
    child_dir = boron.Information(name="nested", kind="directory")
    child_dir.children["guide.md"] = boron.Information(name="guide.md", kind="file", content="Guide")
    folder.children["nested"] = child_dir

    calls = {}

    def fake_info_shell(**kwargs):
        calls["folder"] = kwargs["info"]
        calls["title"] = kwargs["info_title"]

    selections = iter(["nested", boron.BACK_TEXT])

    def fake_ui_run(menu, **kwargs):
        return next(selections)

    monkeypatch.setattr(boron, "info_shell", fake_info_shell)
    monkeypatch.setattr(boron, "_ui_run", fake_ui_run)
    monkeypatch.setattr(boron, "keymap", None, raising=False)

    result = boron._information_select_loop(folder, "docs")

    assert result is folder
    assert calls["folder"] is child_dir
    assert calls["title"] == "nested"


def test_information_select_loop_supports_bookmark_lookup_without_file(monkeypatch):
    info = boron.Information(name="b_GamingInformation", kind="directory")
    info.children["README.md"] = boron.Information(name="README.md", kind="file", content="# Title\nHello")

    calls = []

    def fake_save_lookup_bookmark(*args, **kwargs):
        calls.append((args, kwargs))
        return "bookmark-path"

    def fake_ui_run(menu, **kwargs):
        return "bookmark this lookup"

    monkeypatch.setattr(boron, "save_lookup_bookmark", fake_save_lookup_bookmark)
    monkeypatch.setattr(boron, "_ui_run", fake_ui_run)
    monkeypatch.setattr(boron, "keymap", None, raising=False)

    result = boron._information_select_loop(info, "b_GamingInformation", source_author="CoolDev", source_title="b_GamingInformation")

    assert result is info
    assert calls
    assert calls[0][0][0] is info
    assert calls[0][0][1] == "CoolDev"
    assert calls[0][0][2] == "b_GamingInformation"


def test_information_select_loop_supports_lookup_bookmark_action(monkeypatch):
    info = boron.Information(name="b_GamingInformation", kind="directory")
    info.children["README.md"] = boron.Information(name="README.md", kind="file", content="# Title\nHello")

    saved = {}

    def fake_save_lookup_bookmark(target_info, author, source_title, bookmarks_dir=None, item_name=None):
        saved["target_info"] = target_info
        saved["author"] = author
        saved["source_title"] = source_title
        saved["item_name"] = item_name
        return Path("/tmp/bookmark.bbm")

    def fake_ui_run(menu, **kwargs):
        return "bookmark this lookup"

    monkeypatch.setattr(boron, "save_lookup_bookmark", fake_save_lookup_bookmark)
    monkeypatch.setattr(boron, "_ui_run", fake_ui_run)
    monkeypatch.setattr(boron, "keymap", None, raising=False)

    result = boron._information_select_loop(info, "b_GamingInformation", source_author="CoolDev", source_title="b_GamingInformation")

    assert result is info
    assert saved["target_info"] is info
    assert saved["author"] == "CoolDev"
    assert saved["source_title"] == "b_GamingInformation"
    assert saved["item_name"] == "b_GamingInformation"


def test_information_select_loop_supports_back_from_directory(monkeypatch):
    folder = boron.Information(name="docs", kind="directory")
    file_entry = boron.Information(name="guide.md", kind="file", content="Guide")
    folder.children["guide.md"] = file_entry

    calls = {"count": 0}

    last_menu = {}

    def fake_ui_run(menu, **kwargs):
        calls["count"] += 1
        last_menu["menu"] = menu
        return boron.BACK_TEXT

    monkeypatch.setattr(boron, "_ui_run", fake_ui_run)
    monkeypatch.setattr(boron, "keymap", None, raising=False)

    result = boron._information_select_loop(folder, "docs")

    assert result is folder
    assert calls["count"] == 1
    assert boron.BACK_TEXT in last_menu["menu"].options


def test_info_shell_directory_lists_child_entries_and_nested_folders(monkeypatch):
    root = boron.Information(name="docs", kind="directory")
    nested = boron.Information(name="nested", kind="directory")
    nested.children["guide.md"] = boron.Information(name="guide.md", kind="file", content="Guide")
    root.children["nested"] = nested
    root.children["README.md"] = boron.Information(name="README.md", kind="file", content="# Title\nHello")

    call_count = 0

    def fake_run(menu, **kwargs):
        nonlocal call_count
        call_count += 1
        options = list(menu.options.keys())
        if call_count == 1:
            assert "nested" in options
            assert "README.md" in options
            return "nested"
        assert "guide.md" in options
        return boron.BACK_TEXT

    monkeypatch.setattr(boron, "run", fake_run)
    monkeypatch.setattr(boron, "keymap", None, raising=False)

    boron.info_shell(
        info=root,
        source_info=root,
        source_info_title="docs",
        source_info_author="CoolDev",
        info_title="docs",
    )

    assert call_count == 2
