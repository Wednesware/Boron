# Lookup

The lookup helper provides the same functionality as the main Boron CLI entrypoint.

Use it either as:

```bash
boron lookup "CoolDev's Gaming Information"
```

or as:

```bash
lookup "CoolDev's Gaming Information"
```

The command resolves the identifier, downloads the latest GitHub release, builds an `Information` tree, discards the extracted files, and prints a tree view without file contents.

It is intentionally lightweight and can be used in scripts by importing from the root package:

```python
from boron import lookup

info = lookup("ashley myers' movies")
print(info.render())
```