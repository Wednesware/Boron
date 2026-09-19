[![Wednesware](wednesware.png)](https://wednesware.org)

# Boron

Library-themed Python library and CLI for resolving information and documentation from Boron repositories on GitHub.

## Installation

> `n2 get boron && n2 install-cache boron`

### Uninstall

> `n2 uninstall boron`

## Quick start

### Resolve a normal Boron repository

```python
from boron import parse_identifier, lookup

author, repo = parse_identifier("CoolDev's Gaming Information")
print(author, repo)  # CoolDev, b_GamingInformation

info = lookup("CoolDev's Gaming Information")
print(info.name)
print(info["README.md"].content[:120])
```

### Fetch only documentation from a repo

```python
from boron import lookup

info = lookup("documentation of CoolDev's Gaming Information")
print(info.name)  # b_GamingInformation
print(list(info.children.keys()))
print(info["README.md"].content[:200])
```

### Fetch only the license text

```python
from boron import lookup

info = lookup("license of CoolDev's Gaming Information")
print(info.name)  # b_GamingInformation
print(list(info.children.keys()))
print(info["LICENSE.md"].content[:200])
```

### Work with saved bookmarks

```python
from boron import save_bookmark, list_bookmarks

path = save_bookmark("# Example\nHello", "CoolDev", "b_GamingInformation", "README.md")
print(path)
print([entry["label"] for entry in list_bookmarks()])
```

## Dependencies

- Python 3.12+
- venv (`pip install virtualenv`) for the custom environment.
- **Boron handles other dependencies automatically in its custom environment assuming you use the CLI/command to start it.** These dependencies include the following:
  - Nitrogen 26.59+ (`pip install wwn`) for Wednesware-managed dependencies. These never need to be installed manually.
    - Magnesium
    - Sulfur
    - Fluorine
    - Iodine
    - Neon
  - Webview (`pip install pywebview`) as a Sulfur dependency for the `open in app` action.
  - Pyperclip (`pip install pyperclip`) for the `copy content to clipboard` action.
  - PySide6 (`pip install PySide6`) as a Sulfur dependency for the `open in app` action.
  - qtpy (`pip install qtpy`) as a Sulfur dependency for the `open in app` action.

# Commands

Use Boron from the Python API or the CLI.

```bash
python -m boron --help
python -m boron help
python -m boron license
python -m boron lookup "CoolDev's Gaming Information"
python -m boron lookup "documentation of CoolDev's Gaming Information"
python -m boron lookup "license of CoolDev's Gaming Information"
python -m boron bm
```

## Command behavior

- `help` shows the available CLI commands.
- `license` prints the Boron project license text.
- `lookup <identifier>` resolves and opens a repository snapshot for browsing.
- `lookup "documentation of <author>'s <repo>"` fetches only the README/documentation file for that repository.
- `lookup "license of <author>'s <repo>"` fetches only the LICENSE file for that repository.
- `bm` opens the bookmark manager for saved lookup and file entries.

# Definitions

## `boron`

From the base package, you can import the core Boron helpers and types.

```python
from boron import (
    Information,
    parse_identifier,
    lookup,
    download_release,
    save_bookmark,
    save_lookup_bookmark,
    list_bookmarks,
    load_bookmark,
)
```

### `boron:Information`

`Information` is the tree node object used to represent a repository snapshot. It can represent either a directory or a file, and it stores a name, content, path, and child entries.

```python
info = Information(name="b_GamingInformation", kind="directory")
info.children["README.md"] = Information(
    name="README.md",
    kind="file",
    path="/tmp/README.md",
    content="# Hello\n",
)
```

#### `boron:Information.get(path, default=None)`

Resolve a nested node by slash-delimited path.

```python
readme = info.get("README.md")
print(readme.name)
```

#### `boron:Information.get_file(path, default=None)`

Return file contents for a nested file node, or the default value if the path does not resolve to a file.

```python
text = info.get_file("README.md")
print(text)
```

### `boron:parse_identifier(identifier, no_format=False)`

Normalize a human-readable identifier into the author and repository names expected by Boron.

```python
author, repo = parse_identifier("CoolDev's Gaming Information")
print(author)  # CoolDev
print(repo)    # b_GamingInformation
```

The function also supports the special documentation and license forms:

```python
parse_identifier("documentation of CoolDev's Gaming Information")
# ('CoolDev', 'GamingInformation')

parse_identifier("license of CoolDev's Gaming Information")
# ('CoolDev', 'GamingInformation')
```

### `boron:lookup(identifier, cache_dir=None, offline=False)`

Resolve a Boron repository by identifier, fetch its extracted snapshot, and return an `Information` tree for browsing.

```python
info = lookup("CoolDev's Gaming Information")
print(info.name)
print(info["README.md"].content[:200])
```

If `offline=True`, Boron will prefer a cached lookup. When the identifier starts with `documentation of` or `license of`, only the relevant file is kept in the returned tree.

### `boron:download_release(author, repo_name, cache_dir=None)`

Download and extract the default-branch archive for a Boron repository, returning the extracted root path.

```python
root = download_release("CoolDev", "b_GamingInformation")
print(root)
```

### `boron:save_bookmark(content, author, source_title, item_name, bookmarks_dir=None)`

Save a file snapshot to the bookmark store.

```python
save_bookmark("# Example\nHello", "CoolDev", "b_GamingInformation", "README.md")
```

### `boron:save_lookup_bookmark(info, author, source_title, bookmarks_dir=None, item_name=None)`

Save an entire lookup tree as a bookmark so it can be reopened later.

```python
save_lookup_bookmark(info, "CoolDev", "b_GamingInformation")
```

### `boron:list_bookmarks(bookmarks_dir=None)`

List all saved bookmark entries as metadata dictionaries.

```python
for entry in list_bookmarks():
    print(entry["label"])
```

### `boron:load_bookmark(path)`

Load a bookmark from disk and restore it as either an `Information` tree or a file payload.

```python
loaded = load_bookmark("/path/to/bookmark.bbm")
print(type(loaded).__name__)
```

## `boron.lookup`

The `boron.lookup` module re-exports the public repository lookup API.

```python
from boron.lookup import Information, lookup, download_release
```

### `boron.lookup:lookup(identifier, cache_dir=None, offline=False)`

Equivalent to the package-level lookup helper, intended for callers that want the lookup API without importing the full package namespace.

```python
from boron.lookup import lookup
info = lookup("documentation of CoolDev's Gaming Information")
print(info["README.md"].content)
```

### `boron.lookup:download_release(author, repo_name, cache_dir=None)`

Equivalent to the package-level archive download helper.

```python
from boron.lookup import download_release
root = download_release("CoolDev", "b_GamingInformation")
print(root)
```

## `boron.__main__`

The CLI entry point is exposed through the package module and behaves the same as the installed `boron` command.

```bash
python -m boron lookup "CoolDev's Gaming Information"
```
