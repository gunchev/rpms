#!/usr/bin/env python3
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path


def extract_deb_control(deb_path: str) -> dict:
    if not os.path.isfile(deb_path):
        print(f"Error: Deb file not found: {deb_path}", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        ["dpkg-deb", "--info", deb_path, "control"],
        check=False,
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


# Older debs ship the app icon in a bogus "0x0" hicolor bucket; %prep renames it.
ICON_SIZE_RENAME = {"0x0": "1024x1024"}

# The bundled lms CLI (import/export models from a terminal) lives inside the app
# tree; expose it on PATH as a package-owned symlink.
LMS_CLI_PATH = "/opt/LM-Studio/resources/app/.webpack/lms"
LMS_BIN_PATH = "/usr/bin/lms"
# Duplicates smaller than this save only a block or two; not worth the link churn.
MIN_HARDLINK_BYTES = 16384
# electron-builder updater config. The in-app updater escalates to root to rewrite the
# package-owned /opt/LM-Studio tree and leaves "<file>;<hex ts>" rollback copies behind,
# so the RPM drops it and upgrades stay in the package manager.
UPDATER_CONFIG_PATH = "/opt/LM-Studio/resources/app-update.yml"


def list_deb_data_entries(deb_path: str) -> list:
    """Return (absolute install path, size) for each entry in the deb data archive."""
    result = subprocess.run(
        ["dpkg-deb", "--contents", deb_path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        print(f"Error listing deb contents: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    entries = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 5)
        if len(fields) < 6:
            continue
        # Symlink entries look like "./usr/bin/foo -> /opt/..."
        path = fields[5].split(" -> ", 1)[0].strip()
        if not path:
            continue
        # dpkg reports paths relative to the archive root; make them absolute.
        while path.startswith("./"):
            path = path[2:]
        path = "/" + path if not path.startswith("/") else path
        try:
            size = int(fields[2])
        except ValueError:
            size = 0
        entries.append((path, size))
    return entries


def list_deb_data_paths(deb_path: str) -> list:
    """Return the paths in the deb data archive as absolute install paths."""
    return [path for path, _ in list_deb_data_entries(deb_path)]


def extract_deb_md5sums(deb_path: str) -> dict:
    """Return {absolute install path: md5} from the deb's own md5sums manifest."""
    tmpdir = tempfile.mkdtemp(prefix="lm-studio-control-")
    try:
        result = subprocess.run(
            ["dpkg-deb", "-e", deb_path, tmpdir],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            print(f"Warning: no control archive: {result.stderr}", file=sys.stderr)
            return {}
        manifest = os.path.join(tmpdir, "md5sums")
        if not os.path.isfile(manifest):
            return {}
        sums = {}
        with open(manifest, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "  " not in line:
                    continue
                digest, path = line.rstrip("\n").split("  ", 1)
                while path.startswith("./"):
                    path = path[2:]
                if path:
                    sums["/" + path] = digest.strip()
        return sums
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def find_duplicate_groups(entries: list, md5sums: dict, min_bytes: int) -> list:
    """Group byte-identical files; returns (canonical, duplicates, size) tuples."""
    groups: dict = defaultdict(list)
    for path, size in entries:
        if path.endswith("/") or size < min_bytes:
            continue
        digest = md5sums.get(path)
        if digest:
            groups[digest].append((size, path))

    result = []
    for members in groups.values():
        if len(members) < 2:
            continue
        if len({size for size, _ in members}) != 1:
            continue  # manifest disagrees with the archive listing; leave it alone
        members.sort(key=lambda item: item[1])
        canonical = members[0][1]
        result.append((canonical, [path for _, path in members[1:]], members[0][0]))
    result.sort(key=lambda item: item[2], reverse=True)
    return result


def build_install_snippet(dup_groups: list, lms_cli: bool, strip_updater: bool) -> str:
    """Build the extra %install steps: lms symlink, updater removal, hardlink pass."""
    lines = ['BR="%{buildroot}"']

    if lms_cli:
        lines += [
            "",
            "# Ship the bundled lms CLI on PATH (imports models from a terminal).",
            "# Relative link so it resolves identically on split- and merged-usr hosts.",
            'mkdir -p "$BR/usr/bin"',
            f'ln -sr "$BR{LMS_CLI_PATH}" "$BR{LMS_BIN_PATH}"',
        ]

    if strip_updater:
        lines += [
            "",
            "# Drop the in-app updater: it escalates to root to rewrite /opt/LM-Studio and",
            "# leaves '<file>;<hex timestamp>' rollback copies behind. RPM upgrades go through",
            "# the package manager instead, so the app must not offer its own updates.",
            f'rm -f "$BR{UPDATER_CONFIG_PATH}"',
        ]

    if dup_groups:
        saved = sum(len(dups) * size for _, dups, size in dup_groups)
        lines += [
            "",
            "# Hardlink byte-identical payloads so the RPM stores a single copy",
            f"# ({saved / 1e6:.1f} MB reclaimed once installed).",
        ]
        for canonical, dups, _ in dup_groups:
            for dup in dups:
                lines.append(f'ln -f "$BR{canonical}" "$BR{dup}"')

    return "\n".join(lines) + "\n"


def normalize_path(path: str) -> str:
    """Mirror the %prep icon rename so %files matches the extracted tree."""
    prefix = "/usr/share/icons/hicolor/"
    if not path.startswith(prefix):
        return path
    size, sep, tail = path[len(prefix) :].partition("/")
    if size in ICON_SIZE_RENAME:
        return prefix + ICON_SIZE_RENAME[size] + sep + tail
    return path


def build_files_entries(paths: list, name: str) -> list:
    """Build the %files list from what the deb actually ships."""
    entries = []

    doc_dir = f"/usr/share/doc/{name}"
    if any(p == doc_dir or p.startswith(doc_dir + "/") for p in paths):
        entries.append(doc_dir)

    entries.extend(
        sorted(
            normalize_path(p)
            for p in set(paths)
            if p.startswith("/usr/share/applications/") and not p.endswith("/")
        )
    )

    entries.extend(
        sorted(
            normalize_path(p)
            for p in set(paths)
            if p.startswith("/usr/share/icons/") and not p.endswith("/")
        )
    )

    if any(p == "/opt/LM-Studio" or p.startswith("/opt/LM-Studio/") for p in paths):
        entries.append("/opt/LM-Studio")
    elif any(p.startswith("/opt/") for p in paths):
        entries.append("/opt")

    return entries


def extract_deb_scripts(deb_path: str) -> dict:
    scripts = {}
    for script in ["preinst", "postinst", "prerm", "postrm"]:
        result = subprocess.run(
            ["dpkg-deb", "--info", deb_path, script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0 and result.stdout.strip():
            scripts[script] = result.stdout
    return scripts


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
    output: str,
    deb_filename: str = "",
    data_paths: list | None = None,
):
    name = control.get("Package", "lm-studio")
    version = control.get("Version", "0.0.0")
    major, minor, patch, release = parse_version(version)
    description = control.get("Description", "No description available")
    maintainer = control.get("Maintainer", "Unknown")

    version_release = f"{major}.{minor}.{patch}-{release}"
    changelog_date = subprocess.run(
        ["date", "+%a %b %d %Y"], check=False, capture_output=True, text=True
    ).stdout.strip()

    entries = list_deb_data_entries(deb_filename) if deb_filename else []
    if data_paths is None:
        data_paths = [path for path, _ in entries]
    files_entries = build_files_entries(data_paths or [], name)
    if not files_entries:
        print("Error: no installable paths found in deb data archive", file=sys.stderr)
        sys.exit(1)

    lms_cli = any(path == LMS_CLI_PATH for path, _ in entries)
    if lms_cli:
        files_entries.append(LMS_BIN_PATH)

    strip_updater = any(path == UPDATER_CONFIG_PATH for path, _ in entries)
    md5sums = extract_deb_md5sums(deb_filename) if deb_filename else {}
    dup_groups = find_duplicate_groups(entries, md5sums, MIN_HARDLINK_BYTES)
    install_snippet = build_install_snippet(dup_groups, lms_cli, strip_updater)

    print(f"Discovered {len(files_entries)} %files entries from deb contents")
    if lms_cli:
        print(f"Symlinking {LMS_BIN_PATH} -> {LMS_CLI_PATH}")
    if strip_updater:
        print(f"Removing in-app updater config {UPDATER_CONFIG_PATH}")
    if dup_groups:
        dup_files = sum(len(dups) for _, dups, _ in dup_groups)
        saved = sum(len(dups) * size for _, dups, size in dup_groups)
        print(
            f"Hardlinking {dup_files} identical files in {len(dup_groups)} groups "
            f"({saved / 1e6:.1f} MB reclaimed)"
        )

    source_line = ""
    prep_section = ""
    extra_defines = ""
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

    spec_content = f"""Name: {name}
Version: {major}.{minor}.{patch}
Release: {release}
{extra_defines}{source_line}Summary: {control.get("Description", "").split(chr(10))[0] or "No summary"}
License: see /usr/share/doc/{name}/copyright
Vendor: {maintainer}
URL: https://lmstudio.ai
BuildArch: x86_64

{prep_section}%description
{description.strip()}


%install
rm -rf %{{buildroot}}
mkdir -p %{{buildroot}}
for tree in usr opt; do
    if test -d "$tree"; then
        cp -a "$tree" "%{{buildroot}}/"
    fi
done
{install_snippet}
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

    spec_content += f"""


%files
%defattr(-,root,root,-)
{chr(10).join(files_entries)}


%changelog
* {changelog_date} {maintainer} - {version_release}
- Converted from deb package {version}
"""

    if output == "/dev/stdout" or output == "-":
        print(spec_content)
    else:
        Path(output).write_text(spec_content)
        print(f"Spec file written to: {output}")


def convert_shell_script(script: str, name: str) -> str:
    return script


def main():
    parser = argparse.ArgumentParser(
        description="Generate RPM spec file from Debian package"
    )
    parser.add_argument(
        "deb",
        nargs="?",
        default="LM-Studio-*-x64.deb",
        help="Path to deb package (default: LM-Studio-*-x64.deb)",
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
            output_spec = "lm-studio.spec"

    control = extract_deb_control(deb_path)
    scripts = extract_deb_scripts(deb_path)

    generate_spec(control, scripts, output_spec, deb_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
