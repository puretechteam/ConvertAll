# Contributing

Thanks for helping. Bug reports, new formats and fixes are all welcome.

## Reporting a bug

Open an issue with:

- what you converted (the input and output formats; attach the file if you can share it);
- what happened, and what you expected;
- your ConvertAll version (☰ → *About*) and which engines are installed (`convertall engines`).

Security problems go through [SECURITY.md](SECURITY.md) instead, not a public issue.

## Making a change

```
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
```

Tests for engines you don't have installed skip, so the suite runs on any Windows machine. GitHub Actions runs the same tests and `ruff check` on every pull request.

- **New format:** write one function in `convertall/converters/` with `@converter(inputs={...}, outputs={...}, engine=...)`, add it to `formats.py`, and add a sample to `tests/samples.py`. Routing, the CLI and the window pick it up automatically.
- **Prefer built-in code over engines.** An engine (FFmpeg, LibreOffice, ...) means users install hundreds of megabytes. If a pure-Python library does the job, use it. [meshport](https://github.com/puretechteam/meshport), [packport](https://github.com/puretechteam/packport) and [bookport](https://github.com/puretechteam/bookport) were written for exactly this.
- **Reading text files:** use `convertall.textfile.read_text`, which handles UTF-8, UTF-16 and older Windows encodings.
- **Untrusted input:** people convert files they downloaded. A file may link to others only in its own folder or one level up (`safety.local_file`); never follow absolute or network paths, cap anything that decompresses (`safety.read_capped`), run engines sandboxed where they offer it, and turn library errors into `ConversionError` with a message a user can act on. Add a test that builds the hostile file in code to `tests/test_hardening.py`.
- **Changelog:** add a dated entry to [CHANGELOG.md](CHANGELOG.md) for anything a user would notice.

Keep pull requests to one change each, and match the style of the code around you.

## License

By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE).
