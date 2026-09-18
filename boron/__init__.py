import sys, re, json, shutil, zipfile, subprocess, webbrowser, os
from dataclasses import dataclass, field
from pathlib import Path
import urllib.request
import urllib.error
try:
    from nitrogen import require
    run = require("iodine").run
    Keymap = require("iodine").Keymap
    TextInput = require("iodine.widgets.text_input").TextInput
    SelectMenu = require("iodine.widgets.select").SelectMenu
    Color = require("magnesium.color").Color
    App = require("sulfur").App
    info_window = require("sulfur").info
    error_window = require("sulfur").error
    Terminal = require("neon.terminal").Terminal
    Page = require("fluorine").Page
    div_tag = require("fluorine.structuring").div
    h1_tag = require("fluorine.structuring").h1
    document = require("fluorine.scripting").document
    Script = require("fluorine.scripting").Script
    event = require("fluorine.scripting").event
    title_tag = require("fluorine.structuring").title
except ImportError:
    raise RuntimeError("boron: Nitrogen is not installed. Please install it using 'pip install wwn'.")

VERSION: str = "26.2"

BORON_DIR: Path = Path.home() / ".boron"
DEFAULT_CACHE_DIR: Path = BORON_DIR / "cache"
DEFAULT_BOOKMARKS_DIR: Path = BORON_DIR / "bookmarks"
LOOKUP_HISTORY_FILE: Path = DEFAULT_CACHE_DIR / "lookups.json"
EXIT_TEXT: str = "[exit]"
BACK_TEXT: str = "[back]"

keymap: Keymap = Keymap() # type: ignore
@keymap.on("CTRL_C")
def handle_ctrl_c(_) -> None:
    print("Operation cancelled by user.")
    exit(0)

@dataclass
class Information:
    name: str
    kind: str = "directory"
    content: str | None = None
    path: str | None = None
    children: dict[str, "Information"] = field(default_factory=dict)

    @classmethod
    def from_directory(cls, root: Path, root_name: str | None = None) -> "Information":
        root_name = root_name or root.name
        node = cls(name=root_name, kind="directory", path=str(root))
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith("_") or child.name.startswith("."):
                continue
            if child.is_dir():
                node.children[child.name] = cls.from_directory(child, child.name)
            elif child.is_file():
                try:
                    text = child.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    text = child.read_bytes().decode("utf-8", errors="replace")
                node.children[child.name] = cls(
                    name=child.name,
                    kind="file",
                    path=str(child),
                    content=text,
                )
        return node

    @classmethod
    def from_dict(cls, data: dict[str, any]) -> "Information":
        node = cls(
            name=data.get("name", "root"),
            kind=data.get("kind", "directory"),
            content=data.get("content"),
            path=data.get("path"),
        )
        for key, child in data.get("children", {}).items():
            node.children[key] = cls.from_dict(child)
        return node

    def to_dict(self) -> dict[str, any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "content": self.content,
            "path": self.path,
            "children": {key: child.to_dict() for key, child in self.children.items()},
        }

    def get(self, path: str, default: "Information | str | None" = None) -> "Information | str | None":
        if path is None:
            return default
        parts = [part for part in str(path).replace('\\', '/').strip('/').split('/') if part and part != '.']
        node: "Information | None" = self
        for part in parts:
            if node is None or node.kind != "directory":
                return default
            node = node.children.get(part)
        if node is None:
            return default
        return node

    def __getitem__(self, path: str) -> "Information":
        result = self.get(path, default=None)
        if result is None:
            raise KeyError(path)
        return result

    def get_file(self, path: str, default: str | None = None) -> str | None:
        info = self.get(path, default=None)
        if info is None or not isinstance(info, Information):
            return default
        if info.kind != "file":
            return default
        return info.content

def parse_identifier(identifier: str, no_format: bool = False) -> tuple[str, str]:
    if identifier is None:
        raise ValueError("Boron identifier is required.")

    value = str(identifier).strip().replace("’", "'").replace("`", "'")
    if not value:
        raise ValueError("Boron identifier cannot be empty.")

    match = re.match(r"(?is)^(?P<author>.+?)(?:'s|')\s*(?P<repo>.+)$", value)
    if not match:
        raise ValueError(
            "Identifier must look like \"<author>'s <repo>\" or \"<author name>' <repo>\"."
        )

    author_value = match.group("author").strip()
    repo_value = match.group("repo").strip()

    if not author_value or not repo_value:
        raise ValueError("Identifier must include both an author and a repository name.")
    
    if no_format:
        return author_value, repo_value

    author_name = re.sub(r"[^A-Za-z0-9\s]", "", author_value)
    author_parts = []
    for part in re.split(r"\s+", author_name.strip()):
        cleaned = re.sub(r"[^A-Za-z0-9]", "", part)
        if not cleaned:
            continue
        if cleaned.isupper():
            cleaned = cleaned[:1].upper() + cleaned[1:].lower()
        elif cleaned.islower() and cleaned:
            cleaned = cleaned[:1].upper() + cleaned[1:]
        author_parts.append(cleaned)
    author_name = "".join(author_parts)
    if not author_name:
        raise ValueError("Identifier author could not be resolved.")

    repo_name = re.sub(r"[^A-Za-z0-9]", "", repo_value)
    if not repo_name:
        raise ValueError("Identifier repository name could not be resolved.")
    if repo_name.isupper():
        repo_name = repo_name.lower()
    elif repo_name.islower():
        repo_name = repo_name
    elif repo_name:
        repo_name = repo_name[:1].upper() + repo_name[1:]
    repo_name = f"b_{repo_name}"
    return author_name, repo_name

def _history_path(cache_dir: Path | str | None = None) -> Path:
    path = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    return path / "lookups.json"

def _ensure_boron_dir(boron_dir: Path | str | None = None) -> Path:
    boron_dir = Path(boron_dir) if boron_dir is not None else BORON_DIR
    boron_dir.mkdir(parents=True, exist_ok=True)
    _ensure_cache(boron_dir / "cache")
    _ensure_bookmarks(boron_dir / "bookmarks")
    return boron_dir

def _ensure_cache(cache_dir: Path | str | None = None) -> Path:
    cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

def _ensure_bookmarks(bookmarks_dir: Path | str | None = None) -> Path:
    bookmarks_dir = Path(bookmarks_dir) if bookmarks_dir is not None else DEFAULT_BOOKMARKS_DIR
    bookmarks_dir.mkdir(parents=True, exist_ok=True)
    return bookmarks_dir

def _sanitize_bookmark_part(value: str | None, fallback: str = "bookmark") -> str:
    text = str(value or fallback).strip()
    text = text.replace("/", "_").replace("\\", "_").replace(":", "_")
    text = re.sub(r"[^A-Za-z0-9_. -]", "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or fallback

def _bookmark_path(author: str, source_title: str, item_name: str, bookmarks_dir: Path | str | None = None) -> Path:
    bookmarks_dir = _ensure_bookmarks(bookmarks_dir)
    author_name = _sanitize_bookmark_part(author, "unknown")
    source_name = _sanitize_bookmark_part(source_title, "lookup")
    file_name = _sanitize_bookmark_part(item_name, "bookmark")
    return bookmarks_dir / f"{author_name}--{source_name}--{file_name}.bbm"

def _read_bookmark_record(path: Path) -> dict[str, any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    if not raw.strip():
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        record = dict(payload)
        record.setdefault("kind", "file")
        record.setdefault("author", "unknown")
        record.setdefault("source", "unknown")
        record.setdefault("name", path.stem)
        if "content" not in record and "tree" not in record:
            record["content"] = raw
        return record

    author = "unknown"
    source = "unknown"
    name = path.stem
    if path.name.endswith(".bbm"):
        stem = path.name.removesuffix(".bbm")
        parts = stem.split("--", maxsplit=2)
        if len(parts) == 3:
            author, source, name = parts
    return {
        "kind": "file",
        "author": author,
        "source": source,
        "name": name,
        "content": raw,
    }


def _format_bookmark_name(name: str) -> str:
    text = str(name or "bookmark").strip()
    text = re.sub(r"^b_", "", text, flags=re.IGNORECASE)
    if re.fullmatch(r"[A-Za-z]+\d+", text):
        match = re.match(r"^(?P<label>[A-Za-z]+)(?P<number>\d+)$", text)
        if match:
            label = match.group("label")
            number = match.group("number")
            if len(number) > 1:
                text = f"{label}{number[:1]}.{number[1:]}"
    text = text.replace("_", " ")
    return text.strip() or "bookmark"


def _bookmark_label(record: dict[str, any]) -> str:
    name = _format_bookmark_name(str(record.get("name") or "bookmark").strip())
    source = str(record.get("source") or "unknown").strip()
    author = str(record.get("author") or "unknown").strip()
    kind = str(record.get("kind") or "file").lower()
    if kind == "lookup":
        if author not in {"unknown", ""}:
            return f"{name} from {author}"
        return name
    if source and author not in {"unknown", ""}:
        return f"{name} from {author}'s {source}"
    return name


def save_bookmark(content: str, author: str, source_title: str, item_name: str, bookmarks_dir: Path | str | None = None) -> Path:
    path = _bookmark_path(author, source_title, item_name, bookmarks_dir=bookmarks_dir)
    payload = {
        "kind": "file",
        "author": str(author).strip() or "unknown",
        "source": str(source_title).strip() or "lookup",
        "name": str(item_name).strip() or "bookmark",
        "content": str(content),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def has_bookmark(author: str, source_title: str, item_name: str, bookmarks_dir: Path | str | None = None) -> bool:
    return _bookmark_path(author, source_title, item_name, bookmarks_dir=bookmarks_dir).exists()


def remove_bookmark(author: str, source_title: str, item_name: str, bookmarks_dir: Path | str | None = None) -> bool:
    path = _bookmark_path(author, source_title, item_name, bookmarks_dir=bookmarks_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


def save_lookup_bookmark(info: Information, author: str, source_title: str, bookmarks_dir: Path | str | None = None, item_name: str | None = None) -> Path:
    path = _bookmark_path(author, source_title, item_name or info.name, bookmarks_dir=bookmarks_dir)
    payload = {
        "kind": "lookup",
        "author": str(author).strip() or "unknown",
        "source": str(source_title).strip() or "lookup",
        "name": str(item_name or info.name).strip() or "lookup",
        "tree": info.to_dict(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_bookmark(path: str | Path) -> Information | str:
    bookmark_path = Path(path)
    record = _read_bookmark_record(bookmark_path)
    if not record:
        return ""

    kind = str(record.get("kind", "file")).lower()
    name = str(record.get("name") or bookmark_path.stem).strip() or bookmark_path.stem

    if kind == "lookup":
        tree = record.get("tree")
        if isinstance(tree, dict):
            info = Information.from_dict(tree)
            info.name = name
            return info
        return Information(name=name, kind="directory", path=str(bookmark_path))

    content = record.get("content")
    if not isinstance(content, str):
        content = bookmark_path.read_text(encoding="utf-8") if bookmark_path.exists() else ""
    return Information(name=name, kind="file", content=content, path=str(bookmark_path))


def list_bookmarks(bookmarks_dir: Path | str | None = None) -> list[dict[str, any]]:
    root = _ensure_bookmarks(bookmarks_dir)
    entries: list[dict[str, any]] = []
    for bookmark_path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not bookmark_path.is_file() or bookmark_path.suffix.lower() != ".bbm":
            continue
        record = _read_bookmark_record(bookmark_path)
        if not record:
            continue
        record["path"] = str(bookmark_path)
        record["label"] = _bookmark_label(record)
        entries.append(record)
    return entries


def _is_offline_fallback_error(err: BaseException) -> bool:
    message = str(err).lower()
    return any(
        token in message
        for token in (
            "rate limit",
            "offline",
            "timed out",
            "network",
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
            "failed to establish",
            "no cached copy was found",
        )
    )

def _load_history(cache_dir: Path | str | None = None) -> list[dict[str, any]]:
    history_path = _history_path(cache_dir)
    if not history_path.exists():
        return []
    try:
        raw = json.loads(history_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(raw, list):
        return raw
    return []

def _save_history(entries: list[dict[str, any]], cache_dir: Path | str | None = None) -> None:
    cache_dir = _ensure_cache(cache_dir)
    history_path = cache_dir / "lookups.json"
    history_path.write_text(json.dumps(list(entries), indent=2, sort_keys=True), encoding="utf-8")

def _history_lookup(owner: str, repo_name: str, cache_dir: Path | str | None = None) -> Information | None:
    cache_dir = _ensure_cache(cache_dir)
    for entry in _load_history(cache_dir):
        if entry.get("owner") == owner and entry.get("repo") == repo_name:
            tree = entry.get("tree")
            if isinstance(tree, dict):
                return Information.from_dict(tree)
    return None

def download_release(author: str, repo_name: str, cache_dir: Path | str | None = None) -> Path:
    cache_dir = _ensure_cache(cache_dir)
    api_url = f"https://api.github.com/repos/{author}/{repo_name}"
    token = ""
    try:
        token = subprocess.check_output(["gh", "auth", "token"], text=True, stderr=subprocess.DEVNULL).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        token = ""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"boron/{VERSION}",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        api_url,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.URLError as err:
        if "rate limit" in str(err).lower():
            raise RuntimeError(f"You're being rate limited! Try again later. {err}") from err
        raise RuntimeError(f"Nonexistent lookup.") from err

    default_branch = payload.get("default_branch") or "main"
    archive_url = f"https://github.com/{author}/{repo_name}/archive/refs/heads/{default_branch}.zip"
    archive_path = cache_dir / f"{author}-{repo_name}-{default_branch}.zip"
    if not archive_path.exists():
        urllib.request.urlretrieve(archive_url, archive_path)

    extraction_root = cache_dir / f"{repo_name}-{default_branch}"
    if extraction_root.exists():
        shutil.rmtree(extraction_root)

    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(cache_dir)

    candidate_dirs = sorted(
        [
            item
            for item in cache_dir.iterdir()
            if item.is_dir() and item.name.lower().startswith(repo_name.lower())
        ],
        key=lambda p: p.name.lower(),
    )

    if not candidate_dirs:
        raise RuntimeError(f"Could not locate the extracted default branch snapshot for {author}/{repo_name}.")

    return candidate_dirs[0]

def _effective_download_release():
    module = sys.modules.get("boron.lookup")
    if module is not None and hasattr(module, "download_release"):
        return module.download_release
    return download_release


def lookup(identifier: str, cache_dir: Path | str | None = None, offline: bool = False) -> Information:
    owner, repo_name = parse_identifier(identifier)
    cache_dir = _ensure_cache(cache_dir)

    cached = _history_lookup(owner, repo_name, cache_dir=cache_dir)
    if offline and cached is not None:
        return cached

    try:
        extracted_root = _effective_download_release()(owner, repo_name, cache_dir=cache_dir)
        info = Information.from_directory(extracted_root)
        info.name = repo_name
    except Exception as err:
        if _is_offline_fallback_error(err):
            if cached is not None:
                print(f"Error: {err}")
                return cached
            raise RuntimeError("Offline mode | Information may be outdated or incomplete. No cached copy was found for this lookup.") from err
        raise

    history = _load_history(cache_dir)
    history.append(
        {
            "owner": owner,
            "repo": repo_name,
            "identifier": identifier,
            "tree": info.to_dict(),
        }
    )
    _save_history(history, cache_dir)

    shutil.rmtree(extracted_root, ignore_errors=True)
    return info

def source(force: bool = False, cache_dir: Path | str | None = None, source_file: Path | str | None = None) -> str:
    cache_dir = _ensure_cache(cache_dir)
    history = _load_history(cache_dir)
    if not history:
        generated = "# Boron Sources\n\nNo sources have been looked up yet.\n"
    else:
        lines = ["# Boron Sources", ""]
        seen: set[tuple[str, str]] = set()
        for entry in history:
            owner = entry.get("owner", "unknown")
            repo = entry.get("repo", "unknown")
            key = (str(owner), str(repo))
            if key in seen:
                continue
            seen.add(key)
            git_url = f"https://github.com/{owner}/{repo}"
            lines.append(f"- [{owner}/{repo}]({git_url})")
        generated = "\n".join(lines) + "\n"

    target = Path(source_file) if source_file is not None else Path.cwd() / "SOURCE.md"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""

    if existing == generated:
        return generated

    if not force:
        confirmation = input(f"Write updated source list to {target}? [y/N]: ").strip().lower()
        if confirmation not in {"y", "yes"}:
            return existing or generated

    target.write_text(generated, encoding="utf-8")
    return generated

def _print_help() -> None:
    print(f"\033[94m{Color.bold}Boron v26.1{Color.reset}")
    print(f"{Color.gray}Library-themed Python library and CLI for resolving information and documentation from Boron repositories on GitHub.{Color.reset}")
    print("")
    print("Commands:")
    print("  help                         Show this help message")
    print("  license                      Show the license")
    print("  lookup \"<author>'s <repo>\"   Resolve and look up a Boron repository.")
    print("  bm                           See your bookmarks")

def _print_license() -> None:
    with open(Path(__file__).parent / "LICENSE.md") as file:
        print(file.read())


def source_this(info: Information) -> None:
    if info.path and Path(info.path).exists():
        print(f"Source file: {info.path}")
    else:
        print(f"Source: {info.name}")


def _open_page_in_app(page: Page) -> None: # type: ignore
    try:
        app: App = App(page, silent=True) # type: ignore
        app.open()
        return
    except Exception as exc:  # pragma: no cover - depends on OS desktop backends
        message = str(exc).lower()
        if any(token in message for token in ("gtk", "qt", "pywebview", "gi", "qtpy")):
            print("Desktop app view is unavailable because no GTK/Qt backend is installed.")
            print("Install one of the following:")
            print("  python -m pip install PyQt5 qtpy")
            print("  python -m pip install PySide6 qtpy")
            print("  sudo apt install python3-gi libgtk-3-0 libgtk-3-dev")
            print("Falling back to your browser instead.")
            try:
                webbrowser.open(str(page.build()))
            except Exception:
                pass
            return
        raise


def _information_select_loop(info: Information, title: str, *, source_author: str | None = None, source_title: str | None = None) -> Information:
    options: dict[str, Information] = {}
    for child_name, child in info.children.items():
        if child.kind == "file" and child.content is not None:
            content = child.content.strip()
            if content.startswith("#"):
                heading = content.split("\n", 1)[0].removeprefix("#").strip()
                if "(pinned)" in content.split("\n", 1)[0].lower():
                    options = {heading: child} | options
                else:
                    options |= {heading: child}
                continue
        options[child_name] = child
    options |= {EXIT_TEXT: None}
    while True:
        Terminal.clear()
        answer: str = run(SelectMenu(
            options=options,
            title=title,
        ), global_keymap=keymap)
        if not answer:
            error_window("Invalid selection.")
            continue
        elif answer == EXIT_TEXT:
            handle_ctrl_c(None)
            continue
        elif answer == "---":
            continue
        selected_option = options.get(answer)
        if selected_option is None:
            print("Lookup complete.")
            return info
        if selected_option.content is not None:
            if TextInput is not None:
                try:
                    info_shell(
                        info=selected_option,
                        source_info=info,
                        source_info_title=source_title or info.name,
                        source_info_author=source_author or "unknown",
                        info_title=answer,
                    )
                except KeyboardInterrupt:
                    pass
            else:
                return info


def info_shell(info: Information, source_info: Information, source_info_title: str, source_info_author: str, info_title: str) -> None:
    file_bookmark_label = "unbookmark this file" if has_bookmark(source_info_author, source_info_title, info.name, bookmarks_dir=DEFAULT_BOOKMARKS_DIR) else "bookmark this file"
    lookup_bookmark_label = "unbookmark this lookup" if has_bookmark(source_info_author, source_info_title, source_info.name, bookmarks_dir=DEFAULT_BOOKMARKS_DIR) else "bookmark this lookup"
    options: list[str] = [
        "open in web",
        "open in app",
        "copy content to clipboard",
        file_bookmark_label,
        lookup_bookmark_label,
        "source this",
        BACK_TEXT,
        EXIT_TEXT
    ]
    while True:
        Terminal.clear()
        if info.content is None:
            print("[No file content available.]")
        elif not info.content:
            print("[File content is empty.]")
        elif len(info.content) > 500 or info.content.count("\n") > 20:
            print("[File content is too large to display in the terminal. Please open it in the browser or app instead.]")
        else:
            print(info.content)
        answer: str = run(SelectMenu(
            options=options,
            title=f"{info_title} ({info.name})",
        ), global_keymap=keymap)
        if answer not in options:
            error_window(f"Invalid selection.")
        elif answer == "---":
            pass
        elif answer in ["open in web", "open in app"]:
            page: Page = Page("index") # type: ignore
            page.connect("https://cdn.jsdelivr.net/npm/marked/marked.min.js")
            page.head(
                title_tag (info.name)
            )
            page.style(identifier="body",
                background_color="#050505"
            )
            page.style .content (
                color="#ffffff",
                font_family="arial"
            )
            page.body(
                div_tag .content (info.content)
            )
            page.script(Script(
                "document.querySelector('.content').innerHTML = marked.parse(document.querySelector('.content').textContent);"
            ))
            if answer == "open in app":
                _open_page_in_app(page)
            else:
                webbrowser.open(str(page.build()))
            try:
                built_path = str(page.build())
                if os.path.exists(built_path):
                    os.remove(built_path)
            except Exception:
                pass
        elif answer == "copy content to clipboard":
            try:
                import pyperclip
            except ImportError:
                print(f"boron: Pyperclip is required for this action. Please install it using 'pip install pyperclip'.")
                exit(1)
            pyperclip.copy(info.content)
            info_window("Content copied to clipboard.")
        elif answer in {"bookmark this file", "unbookmark this file"}:
            if answer == "unbookmark this file":
                removed = remove_bookmark(source_info_author, source_info_title, info.name, bookmarks_dir=DEFAULT_BOOKMARKS_DIR)
                info_window("File unbookmarked." if removed else "File was not bookmarked.")
            else:
                save_bookmark(
                    info.content or "",
                    source_info_author,
                    source_info_title,
                    info.name,
                    bookmarks_dir=DEFAULT_BOOKMARKS_DIR,
                )
                info_window("File bookmarked.")
            options[3] = "unbookmark this file" if has_bookmark(source_info_author, source_info_title, info.name, bookmarks_dir=DEFAULT_BOOKMARKS_DIR) else "bookmark this file"
        elif answer in {"bookmark this lookup", "unbookmark this lookup"}:
            if answer == "unbookmark this lookup":
                removed = remove_bookmark(source_info_author, source_info_title, source_info.name, bookmarks_dir=DEFAULT_BOOKMARKS_DIR)
                info_window("Lookup unbookmarked." if removed else "Lookup was not bookmarked.")
            else:
                save_lookup_bookmark(
                    source_info,
                    source_info_author,
                    source_info_title,
                    bookmarks_dir=DEFAULT_BOOKMARKS_DIR,
                )
                info_window("Lookup bookmarked.")
            options[4] = "unbookmark this lookup" if has_bookmark(source_info_author, source_info_title, source_info.name, bookmarks_dir=DEFAULT_BOOKMARKS_DIR) else "bookmark this lookup"
        elif answer == "source this":
            source_this(info)
        elif answer == BACK_TEXT:
            Terminal.clear()
            return
        elif answer == EXIT_TEXT:
            exit(0)
        Terminal.clear()

def lookup_shell(identifier: str) -> Information:
    offline_used = False
    try:
        info: Information = lookup(identifier)
    except Exception as err:
        cached = None
        try:
            owner, repo_name = parse_identifier(identifier)
            cached = _history_lookup(owner, repo_name, cache_dir=DEFAULT_CACHE_DIR)
        except Exception:
            cached = None

        if cached is not None and _is_offline_fallback_error(err):
            print("You are offline, rate-limited or otherwise unable to fetch fresh data. You have the option of loading up a cached snapshot of this information from when you last looked it up.")
            choice = input("Use cached offline data? [Y/n]: ").strip().lower()
            if choice in {"", "y", "yes"}:
                info = cached
                offline_used = True
            else:
                print("Offline lookup cancelled.")
                exit(1)
        else:
            print(f"Error: {err}")
            exit(1)
    if offline_used:
        print("Offline mode | Information may be outdated or incomplete.\n")
    owner, repo_name = parse_identifier(identifier, no_format=True)
    title = identifier
    if offline_used:
        title = f"{title}{Color.gray} | Offline mode | Information may be outdated or incomplete{Color.reset}"
    return _information_select_loop(info, title, source_author=owner, source_title=repo_name)

def _handle_source(force: bool = False, source_path: str | None = None) -> None:
    if source_path is None:
        target = Path.cwd() / "SOURCE.md"
    else:
        target = Path(source_path)
    source(force=force, source_file=target)

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _ensure_boron_dir()

    if not argv or argv[0] in {"help", "-h", "--help"}:
        _print_help()
        return 0

    command = argv[0]
    
    match command:

        case "license":
            _print_license()
            return 0

        case "lookup":
            if len(argv) < 2:
                print("Usage: boron lookup <identifier>")
                return 1
            lookup_shell(argv[1])
            return 0
        
        case "bm":
            bookmarks = list_bookmarks(DEFAULT_BOOKMARKS_DIR)
            if not bookmarks:
                print("...It's very empty in here...")
                return 0

            options = {entry["label"]: entry for entry in bookmarks}
            answer: str = run(SelectMenu(
                options=list(options.keys()),
                title="Bookmarks",
            ))
            if not answer:
                return 0
            if answer not in options:
                error_window("Invalid selection.")
                return 1

            chosen = options[answer]
            loaded = load_bookmark(chosen["path"])
            if isinstance(loaded, Information):
                if loaded.kind == "directory":
                    _information_select_loop(
                        loaded,
                        title=str(chosen.get("label") or loaded.name),
                        source_author=str(chosen.get("author") or "unknown"),
                        source_title=str(chosen.get("source") or loaded.name),
                    )
                    return 0
                info_shell(
                    info=loaded,
                    source_info=loaded,
                    source_info_title=str(chosen.get("source") or "bookmark"),
                    source_info_author=str(chosen.get("author") or "unknown"),
                    info_title=str(chosen.get("name") or loaded.name),
                )
                return 0

            print(loaded)
            return 0

        case _:
            print(f"Unknown command: {command}")
            _print_help()
            return 1

    print(f"Unknown command: {command}")
    _print_help()
    return 1