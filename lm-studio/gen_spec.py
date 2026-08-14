#!/usr/bin/env python3
import argparse
import glob
import os
import re
import subprocess
import sys
from pathlib import Path


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


def generate_spec(control: dict, scripts: dict, output: str, deb_filename: str = ""):
    name = control.get("Package", "lm-studio")
    version = control.get("Version", "0.0.0")
    major, minor, patch, release = parse_version(version)
    description = control.get("Description", "No description available")
    maintainer = control.get("Maintainer", "Unknown")

    version_release = f"{major}.{minor}.{patch}-{release}"
    changelog_date = subprocess.run(
        ["date", "+%a %b %d %Y"], capture_output=True, text=True
    ).stdout.strip()

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
cp -a usr %{{buildroot}}/
cp -a opt %{{buildroot}}/

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
/usr/share/doc/{name}
/usr/share/applications/{name}.desktop
/usr/share/icons/hicolor/1024x1024/apps/{name}.png
/opt/LM-Studio


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
