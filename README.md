[![Wednesware](wednesware.png)](https://wednesware.org)

# Boron

Library-themed Python library and CLI for resolving information and documentation from Boron repositories on GitHub.

## Overview

The project provides:

- `parse_identifier()` to convert a human-readable name into a Boron GitHub repository reference
- `lookup()` to fetch the latest release, walk the files, and return a structured tree
- `source()` to summarize the lookups into Markdown and optionally update `SOURCE.md`
- a CLI named `boron` with commands for help, license, lookup, and source generation

## Installation

From the repository root:

```bash
python -m pip install -e .
```

Then use the CLI:

```bash
boron --help
```

A standalone `lookup` command is also exported via the same entrypoint:

```bash
lookup --help
```

## Dependencies

- Python 3.10+
- Nitrogen 26.58+ (`pip install wwn`)

## Library API

### `parse_identifier(identifier)`

Parses a Boron identifier in either of these forms:

- `"<author>'s <repo name>"`
- `"<author's name if it ends with s>' <repo name>"`

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

Spaces are ignored during normalization, and the repository name always gains the `b_` prefix.

### `lookup(identifier, cache_dir=None)`

Queries the repository metadata for its default branch, downloads the head snapshot from GitHub, unpacks it, walks the directories and files, and returns an `Information` tree object.

```python
from boron import lookup

info = lookup("CoolDev's Gaming Information")
print(info.name)
print(info)
```

Hidden files and directories beginning with `_` or `.` are ignored while building the tree.

### `Information`

`Information` is a tree node used to represent release contents.

```python
a
from boron import Information
```

Properties include:

- `name`: directory or file name
- `kind`: `directory` or `file`
- `content`: file contents when the node is a file
- `path`: original filesystem path
- `children`: nested entries for directory nodes

### `source(force=False, cache_dir=None, source_file=None)`

Generates a readable Markdown source list from the cached lookups and updates `SOURCE.md` when the content differs.

```python
from boron import source

source(force=True)
```

If the file already matches the generated Markdown, the function does nothing.

## CLI

The `boron` command supports:

- `help` or `--help`
- `license`
- `lookup <identifier>`
- `source [--force] [--file path]`
- `version` or `--version`

Examples:

```bash
boron lookup "CoolDev's Gaming Information"
boron source --force
```

The top-level `lookup` command is wired to the same implementation as `boron lookup`.

### CLI lookup output

The lookup mode prints a modern tree view rather than file contents:

```text
b_GamingInformation
├── README.md
├── docs/
│   └── guide.md
├── src/
│   └── main.py
└── assets/
    └── logo.svg
```

## Source Generation Behavior

`source()` checks the lookup history, creates one-line Markdown source entries for each looked-up repository, and updates `SOURCE.md` only when a difference is detected. If `force=True`, it writes immediately without prompting.

## Project Files

- [README.md](README.md)
- [boron/lookup/README.md](boron/lookup/README.md)

## License

This project is licensed under the MIT license.
