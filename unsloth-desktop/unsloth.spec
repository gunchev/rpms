Name: unsloth
Version: 0.1.701
Release: beta
%define __spec_install_post echo 'skipping'
%define _source_filedigest_algorithm md5
%define _binary_filedigest_algorithm md5
%define _unpackaged_files_terminate_build 0
%define __brp_mangle_shebangs /bin/true
Source0: Unsloth-Desktop-0_1_701_beta-Ubuntu.deb
Summary: Unsloth Desktop App
License: AGPL-3.0-only
Vendor: Unsloth AI
URL: https://unsloth.ai/
BuildArch: x86_64
Requires: libappindicator-gtk3
Requires: webkit2gtk4.1
Requires: gtk3
Provides: unsloth-studio-desktop
Conflicts: unsloth-studio-desktop
Obsoletes: unsloth-studio-desktop


%prep

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

%description
Unsloth Desktop App
(none)


%install
rm -rf %{buildroot}
mkdir -p %{buildroot}
cp -a "usr" %{buildroot}/


%post
#!/bin/bash

if hash update-desktop-database 2>/dev/null; then
    update-desktop-database /usr/share/applications || true
fi

if hash gtk-update-icon-cache 2>/dev/null; then
    gtk-update-icon-cache /usr/share/icons/hicolor || true
fi

%postun
#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0
# Post-removal script for the Unsloth Debian package
# Runs non-interactively; never deletes user data or touches other users' homes.

case "${1:-}" in
    upgrade|1|2) exit 0 ;;
esac

exit 0




%files
%defattr(-,root,root,-)
/usr/bin/unsloth-studio
/usr/lib/Unsloth
/usr/share/applications/Unsloth.desktop
/usr/share/icons/hicolor/128x128/apps/unsloth-studio.png
/usr/share/icons/hicolor/32x32/apps/unsloth-studio.png


%changelog
* Thu Aug 13 2026 Unsloth AI - 0.1.701-beta
- Converted from deb package 0.1.701-beta
