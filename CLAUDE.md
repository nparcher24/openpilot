# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **personal fork of sunnypilot** (which is itself a fork of comma.ai's openpilot), developed to run on a **comma 3X** (device codename TIZI). The owner deploys by pushing to GitHub and pulling on-device over the air — **no SSH**. The most important workflows here are *manipulating the code* and *deploying it to the device*, documented below.

## Deploy to the comma 3X (the core workflow)

The device installs a **git branch**, not a GitHub Release. The comma installer clones `github.com/<user>/openpilot.git -b <branch>` (`--depth=1 --recurse-submodules`). Because dev branches have no `prebuilt` marker file, the device compiles on first boot via `launch_chffrplus.sh` → `system/manager/build.py`.

- **GitHub repo:** `nparcher24/openpilot` (PUBLIC). It MUST be named exactly `openpilot` — `selfdrive/ui/installer/installer.cc` hardcodes `/openpilot.git`. The local folder is still named `sunnypilot-ndm`; the git remote already points at `openpilot`.
- **Dev branch:** `ndm-dev` (custom name avoids comma's stock-branch migration). `master` tracks upstream sunnypilot.
- **Install on device** (Custom Software → Advanced screen, type exactly):
  ```
  installer.comma.ai/nparcher24/ndm-dev
  ```
  First build is ~20–40 min on-device. A persistent **"WARNING: This branch is not tested"** alert is normal for any non-official remote (`system/version.py` `sunnypilot_remote` check) — not a fault.
- **Deploy a change (no SSH, no reinstall):** `git push origin ndm-dev` → on device **Settings → Software → check for update → reboot**. The on-device updater (`system/updated/updated.py`) tracks the installed `origin`/branch and pulls new commits; the build runs on the next boot.

### Verifying a fork build is actually running
Two markers currently live on `ndm-dev` (revert once no longer needed — both tagged with `# ndm:` comments / `-ndm` suffix):
- **Teal sidebar** on the home screen — `selfdrive/ui/layouts/sidebar.py` (`_render`, the background `draw_rectangle_rec`).
- **Version suffix** — `sunnypilot/common/version.h` `SUNNYPILOT_VERSION` ends in `-ndm`, shown at Settings → Software → Current Version as `<version> / <commit> / <channel>` (`system/version.py` `ui_description`).

## Common commands

Use the `op` CLI wrapper (`tools/op.sh`); on a fresh machine alias it or call `tools/op.sh`.

```bash
tools/op.sh setup        # install dependencies (uv-based python env + system deps)
tools/op.sh build -j8    # compile (wraps `scons`); use -jN for cores
tools/op.sh lint         # ruff + codespell (matches CI)
tools/op.sh test         # pytest across the repo
tools/op.sh sim          # run the CARLA/metadrive simulator stack on PC
tools/op.sh juggle       # PlotJuggler;  op.sh replay / cabana for log + CAN tools
```

Direct equivalents (when not using the wrapper):
```bash
scons -j$(nproc)                          # build; add --minimal to skip PC-only tools
scons -j$(nproc) --minimal                # what the device build uses
ruff check .                              # lint (config in pyproject.toml, line-length 160)
pytest <path>                             # run tests (config under [tool.pytest.ini_options])
pytest selfdrive/test/test_onroad.py      # a single test file
pytest path/test_foo.py::test_bar         # a single test
pytest -m 'not slow'                      # skip slow tests; `tici` marker = device-only tests
```
Tests run with `-n auto` (xdist) by default. Test discovery covers `common selfdrive system tools cereal sunnypilot`; submodules (`panda`, `opendbc`, `tinygrad_repo`, etc.) are ignored.

## Git LFS — important for this fork

Large assets (fonts, gifs, svgs, and the `.onnx` driving models, 263 objects) are Git LFS, served from sunnypilot's GitLab (`.lfsconfig`). On this Mac, git-lfs is set to **skip-smudge** — checkouts/pulls bring down LFS *pointers*, not the multi-hundred-MB binaries. Prefix git ops with `GIT_LFS_SKIP_SMUDGE=1` to stay fast; run `git lfs pull` only when you actually need the binaries (e.g. a local build). Do NOT change `.gitmodules` / `.lfsconfig` URLs — they must keep resolving against sunnypilot's servers for the device clone to succeed. The `sunnypilot/neural_network_data` submodule commits its models directly (not LFS).

## Architecture (big picture)

**openpilot is a multi-process system,** not a monolith. `system/manager/manager.py` launches independent processes that communicate over **cereal/msgq** pub-sub (capnp messages defined in `cereal/*.capnp`). Key processes: `pandad` (CAN I/O via the `panda` submodule), `camerad` (cameras), `modeld` (the driving neural net, fed by `selfdrive/modeld/models/*.onnx`), `selfdrived`/`controlsd` (planning + control), `locationd` (localization), and the `ui` (the on-screen interface). To trace a feature you typically follow a capnp message from publisher → subscriber across these processes.

**The `sunnypilot/` overlay is the fork's primary pattern.** sunnypilot mirrors openpilot's tree under `sunnypilot/` (`sunnypilot/selfdrive/`, `sunnypilot/system/`, `sunnypilot/common/`, plus features like `mads`, `mapd`, `navd`, `modeld_v2`). sunnypilot-specific behavior, params, and UI live there and are wired in alongside the upstream code. When adding fork features, prefer this overlay over editing upstream files directly — it keeps `master` syncable with upstream. `sunnypilot/common/version.h` (`SUNNYPILOT_VERSION`) is the fork's version of record; `common/version.h` (`COMMA_VERSION`) is upstream's.

**The UI is Python + raylib** (`pyray`/`rl`), not C++/Qt. Screens are composed in `selfdrive/ui/layouts/` (home, sidebar, settings, onboarding) with sunnypilot overrides in `selfdrive/ui/sunnypilot/layouts/`. Colors are `rl.Color(r, g, b, a)`. UI changes don't require a C++ recompile.

**Build/release model.** `SConstruct` detects the device via `/TICI` and treats absence of `.gitattributes` as "release mode". Production/prebuilt branches are produced by `release/build_release.sh` + `release/release_files.py` (run ON tici hardware): they create an orphan branch, copy only whitelisted files (stripping `.git`, LFS, submodules), precompile with `scons`, and `touch prebuilt` so the device skips the on-boot build. This fork uses plain source branches (build-on-boot) for personal dev; prebuilt branches are out of scope unless distributing to others.

## Reference
- Local memory: `~/.claude/projects/-Users-nicholasparrish-Coding-sunnypilot-ndm/memory/` (see `fork-install-setup.md` for verified deploy facts).
- Restore stock sunnypilot on the 3X: install `release-c3.sunnypilot.ai`.
- Official docs: https://docs.sunnypilot.ai/
