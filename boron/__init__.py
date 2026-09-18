import sys, re, json, shutil, zipfile, subprocess
from dataclasses import dataclass, field
from pathlib import Path
import urllib
try:
    from nitrogen import require
except ImportError:
    pass


VERSION: str = "26.1"

DEFAULT_CACHE_DIR = Path.home() / ".boron"
LOOKUP_HISTORY_FILE = DEFAULT_CACHE_DIR / "lookups.json"

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

def parse_identifier(identifier: str) -> tuple[str, str]:
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

def _ensure_cache(cache_dir: Path | str | None = None) -> Path:
    cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

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

def lookup(identifier: str, cache_dir: Path | str | None = None, offline: bool = False) -> Information:
    owner, repo_name = parse_identifier(identifier)
    cache_dir = _ensure_cache(cache_dir)

    cached = _history_lookup(owner, repo_name, cache_dir=cache_dir)
    if offline and cached is not None:
        return cached

    try:
        extracted_root = download_release(owner, repo_name, cache_dir=cache_dir)
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
    print("Boron v26.1")
    print("")
    print("Usage: boron <command> [arguments]")
    print("")
    print("Commands:")
    print("  help        Show this help message")
    print("  license     Show the project license")
    print("  lookup      Look up a Boron identifier and print the tree")
    print("  source      Regenerate or update SOURCE.md")
    print("  version     Show the current version")

def _print_license() -> None:
    with open(Path(__file__).parent / "LICENSE.md") as file:
        print(file.read())

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
    if "require" in globals():
        run = require("iodine").run
        Keymap = require("iodine").Keymap
        try:
            TextInput = require("iodine.widgets.text_input").TextInput
        except Exception:
            TextInput = None
        try:
            SelectMenu = require("iodine.widgets.select").SelectMenu
        except Exception:
            SelectMenu = None
        try:
            Color = require("magnesium.color").Color
        except Exception:
            Color = type("Color", (), {"gray": "", "reset": ""})()
        try:
            info_window = require("sulfur").info
        except Exception:
            info_window = lambda *args, **kwargs: None
        try:
            error_window = require("sulfur").error
        except Exception:
            error_window = lambda *args, **kwargs: None
        try:
            Terminal = require("neon.terminal").Terminal
        except Exception:
            Terminal = type("Terminal", (), {"clear": staticmethod(lambda: None)})
        options: dict[str, Information] = {}
        for child_name, child in info.children.items():
            if child.kind == "file" and child.content is not None:
                content = child.content.strip()
                if content.startswith("#"):
                    if "(pinned)" in content.strip().split("\n", 1)[0].lower():
                        options = {content.removeprefix("#").strip().split("\n", 1)[0]: child} | options
                    else:
                        options |= {content.removeprefix("#").strip().split("\n", 1)[0]: child}
                    continue
            options[child_name] = child
        keymap: Keymap = Keymap() # type: ignore
        @keymap.on("CTRL_Q")
        def handle_ctrl_q(_) -> None:
            info_window(
                "CTRL+Q: Show this help message.\n"
                "CTRL+M: Toggle multi-select mode.\n"
                "CTRL+B: Bookmark selected file.\n"
                "CTRL+SHIFT+B: Bookmark the whole lookup.\n"
                "CTRL+C: Exit the program."
            )
        @keymap.on("CTRL_C")
        def handle_ctrl_c(_) -> None:
            print("Operation cancelled by user.")
            exit(0)
        title = f"{identifier} | CTRL+Q for help"
        if offline_used:
            title = f"{title}{Color.gray} | Offline mode | Information may be outdated or incomplete{Color.reset}"
        while True:
            Terminal.clear()
            answer: str = run(SelectMenu(
                options=options,
                title=title,
            ), global_keymap=keymap, alt_screen=True)
            if not answer:
                error_window(f"Invalid selection.")
                continue
            selected_option = options.get(answer)
            if selected_option is None:
                print("Lookup complete.")
                return info
            enter_to_continue: bool = True
            if selected_option.content is None:
                enter_to_continue = False
            elif isinstance(selected_option.content, str) and not selected_option.content:
                print(f"[File content is empty.]")
            elif len(selected_option.content) > 500 or selected_option.content.count("\n") > 20:
                print(f"[File content is too large to display in the terminal. Press CTRL+D to open it in the browser instead.]")
            else:
                print(selected_option.content)
            if enter_to_continue:
                if TextInput is not None:
                    try:
                        run(TextInput(f"{Color.gray}Press ENTER to continue...{Color.reset}", password=True, mask_char=""))
                    except KeyboardInterrupt:
                        pass
                else:
                    print("Lookup complete.")
                    return info
    else:
        print("Nitrogen is not installed. Could not require necessary libraries to comprehensively display the results.")
        print("Install Nitrogen with `pip install wwn`.")
        exit(1)

def _handle_source(force: bool = False, source_path: str | None = None) -> None:
    if source_path is None:
        target = Path.cwd() / "SOURCE.md"
    else:
        target = Path(source_path)
    source(force=force, source_file=target)

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in {"help", "-h", "--help"}:
        _print_help()
        return 0

    command = argv[0]

    if command in {"version", "--version", "-v"}:
        print(f"Boron v{VERSION}")
        return 0

    if command == "license":
        _print_license()
        return 0

    if command == "lookup":
        if len(argv) < 2:
            print("Usage: boron lookup <identifier>")
            return 1
        lookup_shell(argv[1])
        return 0

    if command == "source":
        args = argv[1:]
        force = "--force" in args
        if "--file" in args:
            index = args.index("--file")
            source_path = args[index + 1] if index + 1 < len(args) else None
        else:
            source_path = None
        _handle_source(force=force, source_path=source_path)
        return 0

    print(f"Unknown command: {command}")
    _print_help()
    return 1