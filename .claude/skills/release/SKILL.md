---
name: release
description: Cut a release - bump the version, build the package, and publish to PyPI. Use only when the user asks to release.
disable-model-invocation: true
---

Argument: the new version (e.g. `0.2.0`). If not given, ask for it.

1. Run the `check` skill; stop if anything fails.
2. Ensure the working tree is clean (`git status`); stop and ask if not.
3. Set the new version in `pyproject.toml` (`[project] version`) and in `src/rate_limiter/__init__.py` if it defines `__version__`.
4. Build: `rm -rf dist && python -m build`.
5. Verify: `python -m twine check dist/*`.
6. **Ask the user to confirm** before publishing; PyPI uploads cannot be undone.
7. Publish: `python -m twine upload dist/*`.
8. Report the version published. Leave committing and tagging to the user.

Requires `build` and `twine` (`pip install build twine`).
