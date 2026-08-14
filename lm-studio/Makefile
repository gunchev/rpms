DEB ?= $(shell ls LM-Studio-*-x64.deb 2>/dev/null | head -1)
SPEC ?= lm-studio.spec
RPM_DIR ?= rpms
BUILD_ROOT := lm-studio-buildroot


.PHONY: help
help:
	@echo "LM Studio RPM Builder"
	@echo ""
	@echo "Usage:"
	@echo "  make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  download     Download latest deb package from lmstudio.ai"
	@echo "  spec         Generate spec file from deb package"
	@echo "  rpm          Build RPM using rpmbuild (local)"
	@echo "  mock         Build SRPM and RPM using mock"
	@echo "  all          Download, generate spec, and build RPM using mock"
	@echo "  sources      Download/verify sources for spec"
	@echo "  clean        Remove build artifacts"
	@echo "  test         Test metadata extraction"
	@echo "  install-deps Install required build dependencies"
	@echo ""
	@echo "Variables:"
	@echo "  DEB          Path to deb package (default: first LM-Studio-*-x64.deb)"
	@echo "  SPEC         Output spec file path (default: auto-generated)"
	@echo "  RPM_DIR      Directory for RPM output (default: ./rpms/)"



.PHONY: all
all: download spec mock



.PHONY: download
download:
	@echo "Downloading latest LM Studio deb package..."
	@url=$$(curl -sI -L 'https://lmstudio.ai/download/latest/linux/x64?format=deb' | grep -i '^location:' | tail -1 | tr -d '\r' | cut -d ' ' -f 2-); \
	if [ -z "$$url" ]; then \
		echo "Error: Could not get download URL"; \
		exit 1; \
	fi; \
	echo "Downloading: $$url"; \
	curl -C - -L -O "$$url"
	@echo "Download complete"


.PHONY: spec
spec: gen_spec.py
	@echo "Generating spec file from deb package..."
	./gen_spec.py "$(DEB)" -o "$(SPEC)"


.PHONY: rpm
rpm: spec
	@echo "Building RPM package..."
	rpmbuild -bb --target x86_64 --define "_sourcedir $(CURDIR)" "$(SPEC)"
	@echo "RPM built successfully!"



.PHONY: sources
sources:
	@spectool -g -S ./*.spec



.PHONY: mock
mock: spec sources
	@echo "Building SRPM with mock..."
	mkdir -p "$(RPM_DIR)"
	mock --buildsrpm --sources=./ --spec ./*.spec --resultdir="$(RPM_DIR)/"
	@echo "Building RPM with mock..."
	mkdir -p "$(RPM_DIR)"
	mock --rebuild "$(RPM_DIR)"/*.src.rpm --resultdir="$(RPM_DIR)/"
	@echo "RPM built successfully in $(RPM_DIR)/"



.PHONY: clean
clean:
	rm -rf "$(BUILD_ROOT)" "$(RPM_DIR)" lm-studio.spec *.rpm lm-studio/
	@echo "Cleaned build artifacts"



.PHONY: test
test:
	@echo "Testing deb package metadata extraction..."
	./gen_spec.py "$(DEB)" -o /dev/stdout



.PHONY: install-deps
install-deps:
	@echo "Installing build dependencies..."
	@if command -v apt-get >/dev/null 2>&1; then \
		sudo apt-get install -y rpm build-essential dpkg-dev mock rpm curl; \
	elif command -v dnf >/dev/null 2>&1; then \
		sudo dnf install -y rpm-build dpkg mock curl; \
	elif command -v yum >/dev/null 2>&1; then \
		sudo yum install -y rpm-build dpkg mock curl; \
	elif command -v zypper >/dev/null 2>&1; then \
		sudo zypper install -y rpm-build dpkg mock curl; \
	else \
		echo "Cannot detect package manager. Please install: rpm-build, dpkg-dev, mock, curl"; \
		exit 1; \
	fi
