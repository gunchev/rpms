# Unsloth Desktop RPM Package Builder

Convert the Unsloth Desktop Debian package to RPM format.

## Requirements

- `dpkg-dev` - for extracting Debian package metadata
- `rpmbuild` - for building RPM packages
- `python3` - for the spec generator script

Install dependencies:

```bash
make install-deps
```

## Usage

```bash
make              # Show help (default)
make spec         # Generate spec from deb
make rpm          # Build RPM from spec
make all          # Download, generate spec, and build RPM using mock
```

Download the current release deb manually from the
[Unsloth releases page](https://github.com/unslothai/unsloth/releases)
or let `make download` fetch the latest one from the GitHub API.

Current releases use `Unsloth-Desktop-Ubuntu.deb` without a version in the
filename. Both Make and `./gen_spec.py` prefer that file and fall back to
legacy `Unsloth-Desktop-*-Ubuntu.deb` names. The RPM version is read from
the Debian package's `Version` field. `make download` replaces the local
file after a successful download so successive releases with the same
filename are updated correctly.

## Variables

| Variable | Description | Default |
|----------|--------------|---------|
| `DEB` | Path to deb package | `Unsloth-Desktop-Ubuntu.deb`, then first legacy `Unsloth-Desktop-*-Ubuntu.deb` |
| `SPEC` | Output spec file | `unsloth.spec` |
| `RPM_DIR` | RPM output directory | `./rpms/` |

## Files

- `.editorconfig` - Editor configuration for consistent formatting
- `.gitignore` - Git ignore rules for build artifacts
- `gen_spec.py` - Extracts metadata from deb and generates spec file
- `Makefile` - Automates the build process
- `unsloth.spec` - RPM spec file (generated, not committed)
- `*.rpm` - RPM packages (built, not committed)

## Why this isn't just the LM Studio template

Unsloth Desktop's `.deb` is laid out very differently from LM Studio's
Electron package, so `gen_spec.py` can't hardcode paths the way a
single-product script normally would:

- Everything ships under `/usr` — there is no `/opt/<App>` tree, so
  `%install` only `cp -a`s the top-level directories that are actually
  present in the deb (checked via `dpkg-deb --contents`, not assumed).
- The desktop file (`Unsloth.desktop`) and icon base name
  (`unsloth-studio`) don't match the package name (`unsloth`), so `%files`
  is built by walking the deb's real file list rather than guessing
  `%{name}.desktop` / `%{name}.png`. Directories already owned by the
  `filesystem` and `hicolor-icon-theme` packages (`/usr`, `/usr/bin`,
  `/usr/share/icons/hicolor/**`, etc.) are excluded so we don't fight
  those packages for ownership; only the app's own files/dirs
  (`/usr/bin/unsloth-studio`, `/usr/lib/Unsloth`, the desktop file, the
  two icons) are claimed.
- There's no `/usr/share/doc/<pkg>/copyright`, so the license is read
  from an `SPDX-License-Identifier` line found in the deb's maintainer
  scripts or bundled data instead (resolves to `AGPL-3.0-only` here).
- The deb's `Depends:` field lists Debian package names
  (`libwebkit2gtk-4.1-0`, `libgtk-3-0`, `libappindicator3-1`), which don't
  exist under those names on Fedora. `gen_spec.py` maps them to the
  matching Fedora packages (`webkit2gtk4.1`, `gtk3`,
  `libappindicator-gtk3`) via a small `DEB_TO_RPM_DEPS` table. Verified
  against Fedora 44 — re-check package names if targeting a different
  release, since webkit2gtk/appindicator naming has changed across Fedora
  versions before. `libappindicator-gtk3` matters in particular: it's a
  runtime `dlopen()` dependency for the tray icon, not a linked `.so`, so
  `rpmbuild`'s automatic ELF-dependency scan won't find it on its own —
  the explicit `Requires:` is what pulls it in.
- The deb's `Provides`/`Conflicts`/`Replaces: unsloth-studio-desktop` are
  carried over to RPM `Provides`/`Conflicts`/`Obsoletes` so package
  managers still treat this as the app renamed from
  `unsloth-studio-desktop`.

## Customization

Edit `gen_spec.py` to customize the spec generation logic, such as:
- `DEB_TO_RPM_DEPS` — Debian-to-Fedora dependency name mapping
- `STANDARD_DIRS` / `HICOLOR_DIR_RE` — which directories are excluded from
  `%files` because another package already owns them
- Pre/post install scripts
- File ownership
