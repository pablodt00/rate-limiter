---
name: release
description: Prepare a release - bump the version, update the changelog and verify the build; publishing is done by the publish workflow. Use only when the user asks to release.
disable-model-invocation: true
---

Argument: the new version (e.g. `0.2.0`). If not given, ask for it.

1. Run the `check` skill; stop if anything fails.
2. Ensure the working tree is clean (`git status`); stop and ask if not.
3. Set the new version in `pyproject.toml` (`[project] version`); `rate_limiter.__version__` is read from the package metadata.
4. Move the `CHANGELOG.md` "Unreleased" entries under a heading for the new version.
5. Build locally to verify: `rm -rf dist && python -m build && python -m twine check dist/*`.
6. Leave committing to the user, then tell them to tag `v<version>` and publish a GitHub Release. The
   `publish` workflow (`.github/workflows/publish.yml`) uploads to PyPI using the `PYPI_API_TOKEN` secret; do not
   run `twine upload` by hand.
7. Report the version prepared and what is left for the user to do.

Requires `build` and `twine` (`pip install build twine`).
