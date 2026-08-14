# LM Studio RPM Package Builder

Convert LM Studio Debian packages to RPM format.

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
make all          # Build both spec and RPM
```

## Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEB` | Path to deb package | First `LM-Studio-*-x64.deb` found |
| `SPEC` | Output spec file | Auto-generated from deb name |
| `RPM_DIR` | RPM output directory | `.` |

## Files

- `.editorconfig` - Editor configuration for consistent formatting
- `.gitignore` - Git ignore rules for build artifacts
- `gen_spec.py` - Extracts metadata from deb and generates spec file
- `Makefile` - Automates the build process
- `lm-studio.spec` - RPM spec file (generated)
- `*.rpm` - RPM packages (built)

## Customization

Edit `gen_spec.py` to customize the spec generation logic, such as:
- RPM dependencies
- Pre/post install scripts
- File ownership
