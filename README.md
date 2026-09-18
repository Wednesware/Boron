[![Wednesware](wednesware.png)](https://wednesware.org)

# Boron

Library-themed Python library and CLI for resolving information and documentation from Boron repositories on GitHub.

It is designed for looking up Wednesware-style Boron repositories, caching results locally, and inspecting the repo structure without needing to clone or manually navigate the GitHub archive.

## What Boron does today

The implementation currently includes:

- `parse_identifier()` to normalize a friendly name into a GitHub repository owner and Boron repo slug
- `download_release()` to fetch the default-branch archive from GitHub and extract it to the cache
- `lookup()` to find or refresh a repository snapshot, then return an `Information` tree
- `Information` objects for directory/file traversal and nested file access
- local lookup history and offline fallback behavior from `~/.boron/cache/lookups.json`
- bookmark support for saving files and lookups for later browsing
- a terminal-based interactive browser for file content, web/app opening, and clipboard copy
- a small CLI with `help`, `license`, `lookup`, and `bm` commands

## Installation

From the repository root:

```bash
python -m pip install -e .
```

Required runtime dependencies:

- Python 3.10+
- Nitrogen (`pip install wwn`)

Optional dependencies:

- `pyperclip` for the clipboard action

  ```bash
  python -m pip install pyperclip
  ```

- desktop app preview support when using the `open in app` action on Linux

  ```bash
  python -m pip install PyQt5 qtpy
  # or
  python -m pip install PySide6 qtpy
  # or on Debian/Ubuntu:
  sudo apt install python3-gi libgtk-3-0 libgtk-3-dev
  ```

If a GTK or Qt backend is unavailable, Boron falls back to opening the generated page in the browser instead of crashing.

## Library API

### `parse_identifier(identifier, no_format=False)`

Normalizes a human-readable identifier into `(author, repo_name)`.

Examples:

```python
from boron import parse_identifier

parse_identifier("CoolDev's Gaming Information")
# ('CoolDev', 'b_GamingInformation')

parse_identifier("Johnathan John's PLAQUE INFO")
# ('JohnathanJohn', 'b_plaqueinfo')

parse_identifier("ashley myers' movies")
# ('AshleyMyers', 'b_movies')
```

The repo name is normalized to a Boron-style name with a `b_` prefix, and spaces are ignored during normalization.

### `lookup(identifier, cache_dir=None, offline=False)`

Looks a repository up by identifier, downloads the default branch snapshot from GitHub, walks the extracted tree, and returns an `Information` object.

```python
from boron import lookup

info = lookup("CoolDev's Gaming Information")
print(info.name)
print(info)
```

Behavior:

- the default branch archive is fetched from GitHub
- extracted directories beginning with `_` or `.` are excluded from the tree
- previously seen lookups are cached in `lookups.json`
- when `offline=True`, Boron will prefer a cached copy if one exists
- if the network call fails for offline/rate-limit-style conditions, Boron can fall back to cached history instead of failing immediately

### `download_release(author, repo_name, cache_dir=None)`

Downloads and extracts the repo archive for the default branch to the local cache directory and returns the extracted directory path.

```python
from boron import download_release

root = download_release("CoolDev", "b_GamingInformation")
print(root)
```

### `Information`

`Information` is the tree node used to represent a file system snapshot.

```python
from boron import Information
```

Attributes:

- `name`: the node name
- `kind`: either `directory` or `file`
- `content`: file contents for file nodes
- `path`: original filesystem path
- `children`: nested entries for directory nodes

Useful helpers:

```python
info["README.md"]
info.get("docs/guide.md")
info.get_file("docs/guide.md")
```

### `source(force=False, cache_dir=None, source_file=None)`

Creates a Markdown summary of the cached Boron lookups and writes it to a target file when the content differs.

```python
from boron import source

source(force=True)
```

This writes a list of deduplicated repository entries such as:

```md
# Boron Sources

- [CoolDev/b_GamingInformation](https://github.com/CoolDev/b_GamingInformation)
- [JohnathanJohn/b_plaqueinfo](https://github.com/JohnathanJohn/b_plaqueinfo)
```

If the destination file already matches the generated content, the function returns early and does nothing.

### Bookmarks

Boron includes bookmark helpers for saving and restoring lookup snapshots or file content:

```python
from boron import (
    save_bookmark,
    save_lookup_bookmark,
    list_bookmarks,
    load_bookmark,
)
```

These write `.bbm` files under the Boron bookmark directory and restore them as either `Information` trees or plain file content.

## CLI

The project exposes a terminal CLI via `python -m boron` and, when installed as a console script, `boron`.

Current commands:

```bash
python -m boron --help
python -m boron help
python -m boron license
python -m boron lookup "CoolDev's Gaming Information"
python -m boron bm
```

Command behavior:

- `help` shows the available commands
- `license` prints the project license text
- `lookup <identifier>` fetches the repo, renders the interactive file tree, and lets you open files in the browser/app, copy content, or bookmark them
- `bm` opens the bookmark manager and lets you revisit saved lookups and files

### Interactive lookup flow

The lookup screen is terminal-driven and has options such as:

- open in web
- open in app
- copy content to clipboard
- bookmark this file
- bookmark this lookup
- source this
- back
- exit

## Cache and offline behavior

Boron stores lookup history in a local cache under:

```text
~/.boron/cache/lookups.json
```

This cache is used to:

- avoid re-downloading same repos repeatedly
- serve cached snapshots when the network is unavailable or GitHub rate-limits requests
- supply historical data for offline browsing in the interactive lookup UI

## Repository layout

```text
boron/
  __init__.py
  __main__.py
  lookup.py

tests/
  test_boron.py
```

## License

This project is licensed under the MIT License.
