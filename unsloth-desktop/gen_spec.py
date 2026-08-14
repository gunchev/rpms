#!/usr/bin/env python3
import argparse
import glob
import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_SPEC_NAME = "unsloth.spec"

# Debian package name -> Fedora package name for runtime Requires.
# Verified against this box's Fedora release; re-check when targeting a
# different Fedora version, package names for webkit2gtk/appindicator have
# moved before.
DEB_TO_RPM_DEPS = {
    "libappindicator3-1": "libappindicator-gtk3",
    "libwebkit2gtk-4.1-0": "webkit2gtk4.1",
    "libgtk-3-0": "gtk3",
}

# Directories owned by filesystem/hicolor-icon-theme: never claim them in
# %files, only the files shipped inside them.
STANDARD_DIRS = {
    "usr",
    "usr/bin",
    "usr/sbin",
    "usr/lib",
    "usr/lib64",
    "usr/share",
    "usr/share/applications",
    "usr/share/icons",
    "usr/share/pixmaps",
    "usr/share/doc",
    "usr/share/mime",
    "usr/share/mime/packages",
}
HICOLOR_DIR_RE = re.compile(r"^usr/share/icons/hicolor(/.*)?$")
SPDX_RE = re.compile(r"SPDX-License-Identifier:\s*(\S+)")


def extract_deb_control(deb_path: str) -> dict:
    if not os.path.isfile(deb_path):
        print(f"Error: Deb file not found: {deb_path}", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        ["dpkg-deb", "--info", deb_path, "control"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        print(f"Error extracting control: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    control = {}
    current_key = None
    for line in result.stdout.splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            control[current_key] = value.strip()
        elif current_key and line and line[0].isspace():
            control[current_key] += "\n" + line.strip()
    return control


def extract_deb_scripts(deb_path: str) -> dict:
    scripts = {}
    for script in ["preinst", "postinst", "prerm", "postrm"]:
        result = subprocess.run(
            ["dpkg-deb", "--info", deb_path, script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0 and result.stdout.strip():
            scripts[script] = result.stdout
    return scripts


def extract_deb_contents(deb_path: str) -> list[tuple[str, str]]:
    result = subprocess.run(
        ["dpkg-deb", "--contents", deb_path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        print(f"Error listing contents: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    entries = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        mode, path = parts[0], parts[5]
        if " -> " in path:
            path = path.split(" -> ", 1)[0]
        path = path.removeprefix("./")
        if not path:
            continue
        kind = "d" if mode.startswith("d") else "f"
        entries.append((kind, path))
    return entries


def toplevel_dirs(entries: list[tuple[str, str]]) -> list[str]:
    return sorted({path for kind, path in entries if kind == "d" and "/" not in path})


def is_standard_dir(path: str) -> bool:
    return path in STANDARD_DIRS or bool(HICOLOR_DIR_RE.match(path))


def owned_paths(entries: list[tuple[str, str]]) -> list[str]:
    dirs = sorted({path for kind, path in entries if kind == "d"})
    files = sorted({path for kind, path in entries if kind == "f"})

    candidate_dirs = [d for d in dirs if not is_standard_dir(d)]
    owned_dirs: list[str] = []
    for d in sorted(candidate_dirs, key=lambda p: p.count("/")):
        if not any(d == parent or d.startswith(parent + "/") for parent in owned_dirs):
            owned_dirs.append(d)

    owned_files = [
        f for f in files if not any(f == d or f.startswith(d + "/") for d in owned_dirs)
    ]
    return sorted(owned_dirs + owned_files)


def extract_deb_license(
    deb_path: str, scripts: dict, entries: list[tuple[str, str]]
) -> str | None:
    for content in scripts.values():
        match = SPDX_RE.search(content)
        if match:
            return match.group(1)

    # Some packages ship the license header only in bundled data files (not
    # maintainer scripts), e.g. an installer script under /usr/lib. Search
    # the raw data archive bytes rather than extracting to a temp dir.
    result = subprocess.run(
        ["dpkg-deb", "--fsys-tarfile", deb_path], capture_output=True
    )
    if result.returncode == 0:
        match = re.search(rb"SPDX-License-Identifier:\s*(\S+)", result.stdout)
        if match:
            return match.group(1).decode("ascii", "replace")

    name = None
    for _, path in entries:
        if path.startswith("usr/share/doc/") and path.count("/") == 2:
            name = path.split("/")[2]
            break
    if name:
        return f"see /usr/share/doc/{name}/copyright"
    return None


def build_requires(control: dict) -> list[str]:
    depends = control.get("Depends", "")
    requires = []
    for entry in depends.split(","):
        deb_name = entry.strip().split(" ", 1)[0].strip()
        if not deb_name:
            continue
        rpm_name = DEB_TO_RPM_DEPS.get(deb_name)
        if rpm_name:
            requires.append(rpm_name)
        else:
            requires.append(f"## unmapped debian dep: {deb_name}")
    return requires


def parse_version(version_str: str) -> tuple:
    if ":" in version_str:
        version_str = version_str.split(":", 1)[1]
    release = "1"
    if "-" in version_str:
        parts = version_str.rsplit("-", 1)
        if len(parts) == 2:
            version_str = parts[0]
            release = parts[1]
    elif "+" in version_str:
        parts = version_str.rsplit("+", 1)
        if len(parts) == 2 and parts[1].isdigit():
            version_str = parts[0]
            release = parts[1]
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version_str)
    if match:
        return (*match.groups(), release)
    match = re.match(r"(\d+)\.(\d+)", version_str)
    if match:
        return (*match.groups(), "0", release)
    return ("0", "0", "0", release)


def generate_spec(
    control: dict,
    scripts: dict,
    entries: list[tuple[str, str]],
    output: str,
    deb_filename: str = "",
):
    name = control.get("Package", "unsloth")
    version = control.get("Version", "0.0.0")
    major, minor, patch, release = parse_version(version)
    description = control.get("Description", "No description available")
    maintainer = control.get("Maintainer", "Unknown")
    url = control.get("Homepage", "https://unsloth.ai/")

    version_release = f"{major}.{minor}.{patch}-{release}"
    changelog_date = subprocess.run(
        ["date", "+%a %b %d %Y"], capture_output=True, text=True
    ).stdout.strip()

    license_line = extract_deb_license(deb_filename, scripts, entries) or "Unspecified"

    requires_lines = build_requires(control)
    requires = "\n".join(
        line if line.startswith("##") else f"Requires: {line}"
        for line in requires_lines
    )

    provides_conflicts = ""
    if control.get("Provides"):
        provides_conflicts += f"Provides: {control['Provides']}\n"
    if control.get("Conflicts"):
        provides_conflicts += f"Conflicts: {control['Conflicts']}\n"
    if control.get("Replaces"):
        provides_conflicts += f"Obsoletes: {control['Replaces']}\n"

    source_line = ""
    prep_section = ""
    extra_defines = ""
    install_copy = ""
    if deb_filename:
        source_line = f"Source0: {deb_filename}\n"
        extra_defines = (
            "%define __spec_install_post echo 'skipping'\n"
            "%define _source_filedigest_algorithm md5\n"
            "%define _binary_filedigest_algorithm md5\n"
            "%define _unpackaged_files_terminate_build 0\n"
            "%define __brp_mangle_shebangs /bin/true\n"
        )
        prep_section = (
            "\n%prep\n"
            + """
ar x "%{SOURCE0}"
if test -f data.tar.xz; then
    tar xf data.tar.xz
elif test -f data.tar.gz; then
    tar xzf data.tar.gz
elif test -f data.tar.zst; then
    tar xzf data.tar.zst
fi
rm -f debian-binary control.tar.* data.tar.*
if test -d "./usr/share/icons/hicolor/0x0"; then
    mv "./usr/share/icons/hicolor/0x0" "./usr/share/icons/hicolor/1024x1024"
fi

"""
        )
        dirs = toplevel_dirs(entries) or ["usr"]
        install_copy = "\n".join(f'cp -a "{d}" %{{buildroot}}/' for d in dirs)

    files_list = "\n".join(f"/{path}" for path in owned_paths(entries))

    spec_content = f"""Name: {name}
Version: {major}.{minor}.{patch}
Release: {release}
{extra_defines}{source_line}Summary: {control.get("Description", "").split(chr(10))[0] or "No summary"}
License: {license_line}
Vendor: {maintainer}
URL: {url}
BuildArch: x86_64
{requires}
{provides_conflicts}
{prep_section}%description
{description.strip()}


%install
rm -rf %{{buildroot}}
mkdir -p %{{buildroot}}
{install_copy}

"""

    if "preinst" in scripts:
        spec_content += f"""
%preinst
{scripts["preinst"]}
"""

    if "postinst" in scripts:
        spec_content += f"""
%post
{scripts["postinst"]}
"""
    else:
        spec_content += """
%post
#!/bin/bash

if hash update-desktop-database 2>/dev/null; then
    update-desktop-database /usr/share/applications || true
fi

if hash gtk-update-icon-cache 2>/dev/null; then
    gtk-update-icon-cache /usr/share/icons/hicolor || true
fi
"""

    if "prerm" in scripts:
        spec_content += f"""
%prerm
{scripts["prerm"]}
"""

    if "postrm" in scripts:
        spec_content += f"""
%postun
{scripts["postrm"]}
"""
    else:
        spec_content += """
%postun
#!/bin/bash

if hash update-desktop-database 2>/dev/null; then
    update-desktop-database /usr/share/applications || true
fi
"""

    spec_content += f"""


%files
%defattr(-,root,root,-)
{files_list}


%changelog
* {changelog_date} {maintainer} - {version_release}
- Converted from deb package {version}
"""

    if output == "/dev/stdout" or output == "-":
        print(spec_content)
    else:
        Path(output).write_text(spec_content)
        print(f"Spec file written to: {output}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate RPM spec file from Debian package"
    )
    parser.add_argument(
        "deb",
        nargs="?",
        default="Unsloth-Desktop-*-Ubuntu.deb",
        help="Path to deb package (default: Unsloth-Desktop-*-Ubuntu.deb)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output spec file path (default: derived from deb name)",
    )

    args = parser.parse_args()

    deb_files = glob.glob(args.deb)
    if not deb_files:
        print(f"No deb files found matching: {args.deb}", file=sys.stderr)
        sys.exit(1)

    deb_path = deb_files[0]
    print(f"Processing: {deb_path}")

    if args.output:
        output_spec = args.output
    else:
        deb_name = os.path.basename(deb_path)
        match = re.match(r"(.+?)[-_](\d+[\d.-]*)[-_]", deb_name)
        if match:
            base_name = match.group(1).replace("-", "_")
            output_spec = f"{base_name}.spec"
        else:
            output_spec = DEFAULT_SPEC_NAME

    control = extract_deb_control(deb_path)
    scripts = extract_deb_scripts(deb_path)
    entries = extract_deb_contents(deb_path)

    generate_spec(control, scripts, entries, output_spec, deb_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
