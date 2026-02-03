# GoalStick Makefile
# Build and test targets for Android app and Python code

.PHONY: help android-build android-release android-clean android-install \
        python-venv python-check-venv python-test python-test-cov python-install python-clean \
        service-install service-uninstall service-status service-logs \
        all clean test

# Default target
help:
	@echo "GoalStick Build System"
	@echo ""
	@echo "Android targets:"
	@echo "  android-build    Build debug APK"
	@echo "  android-release  Build release APK"
	@echo "  android-install  Install debug APK to connected device"
	@echo "  android-clean    Clean Android build artifacts"
	@echo ""
	@echo "Python targets:"
	@echo "  python-venv      Create virtual environment (if needed)"
	@echo "  python-test      Run Python unit tests"
	@echo "  python-test-cov  Run tests with coverage report"
	@echo "  python-install   Install Python package in dev mode"
	@echo "  python-clean     Clean Python build artifacts"
	@echo ""
	@echo "Service targets (run on Pi):"
	@echo "  service-install  Install and start systemd service"
	@echo "  service-uninstall Remove systemd service"
	@echo "  service-status   Check service status"
	@echo "  service-logs     Tail the service logs"
	@echo ""
	@echo "Combined targets:"
	@echo "  all              Build everything"
	@echo "  test             Run all tests"
	@echo "  clean            Clean all build artifacts"

# =============================================================================
# Android Targets
# =============================================================================

ANDROID_DIR := Android
GRADLEW := $(ANDROID_DIR)/gradlew

# Java 17 is required for Android builds (Gradle doesn't support Java 25 yet)
JAVA17_HOME := /opt/homebrew/opt/openjdk@17

android-build:
	@echo "Building Android debug APK..."
	cd $(ANDROID_DIR) && JAVA_HOME=$(JAVA17_HOME) ./gradlew assembleDebug
	@echo "APK: $(ANDROID_DIR)/app/build/outputs/apk/debug/app-debug.apk"

android-release:
	@echo "Building Android release APK..."
	cd $(ANDROID_DIR) && JAVA_HOME=$(JAVA17_HOME) ./gradlew assembleRelease
	@echo "APK: $(ANDROID_DIR)/app/build/outputs/apk/release/app-release.apk"

android-install: android-build
	@echo "Installing APK to connected device..."
	adb install -r $(ANDROID_DIR)/app/build/outputs/apk/debug/app-debug.apk

android-clean:
	@echo "Cleaning Android build..."
	cd $(ANDROID_DIR) && JAVA_HOME=$(JAVA17_HOME) ./gradlew clean
	rm -rf $(ANDROID_DIR)/.gradle
	rm -rf $(ANDROID_DIR)/app/build

# =============================================================================
# Python Targets
# =============================================================================

PYTHON_DIR := PythonSrc
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

# Create virtual environment if it doesn't exist
python-venv:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment..."; \
		python3 -m venv $(VENV); \
		echo "Virtual environment created at $(VENV)"; \
	else \
		echo "Virtual environment already exists at $(VENV)"; \
	fi

# Ensure venv exists and has pytest installed
python-check-venv:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Error: Virtual environment not found. Run 'make python-venv' first."; \
		exit 1; \
	fi
	@if [ ! -f "$(PYTEST)" ]; then \
		echo "Installing dev dependencies..."; \
		$(PIP) install -e "$(PYTHON_DIR)[dev]"; \
	fi

python-test: python-check-venv
	@echo "Running Python tests..."
	cd $(PYTHON_DIR) && ../$(PYTEST) -v

python-test-cov: python-check-venv
	@echo "Running Python tests with coverage..."
	cd $(PYTHON_DIR) && ../$(PYTEST) --cov=StickCheck --cov-report=term-missing

python-install: python-venv
	@echo "Installing Python package in dev mode..."
	$(PIP) install -e "$(PYTHON_DIR)[dev]"

python-clean:
	@echo "Cleaning Python build artifacts..."
	rm -rf $(PYTHON_DIR)/*.egg-info
	rm -rf $(PYTHON_DIR)/build
	rm -rf $(PYTHON_DIR)/dist
	rm -rf $(PYTHON_DIR)/.pytest_cache
	rm -rf $(PYTHON_DIR)/StickCheck/__pycache__
	rm -rf $(PYTHON_DIR)/tests/__pycache__
	find $(PYTHON_DIR) -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find $(PYTHON_DIR) -type f -name "*.pyc" -delete 2>/dev/null || true

# =============================================================================
# Combined Targets
# =============================================================================

all: android-build python-install
	@echo "Build complete!"

test: python-test
	@echo "All tests passed!"

clean: android-clean python-clean
	@echo "Clean complete!"

# =============================================================================
# Service Targets (run on Raspberry Pi)
# =============================================================================

SERVICE_TEMPLATE := $(PYTHON_DIR)/goalstick.service
INSTALL_DIR := $(shell pwd)

service-install:
	@echo "Installing GoalStick systemd service..."
	@echo "Install directory: $(INSTALL_DIR)"
	@# Create config and log directories
	sudo mkdir -p /etc/goalstick
	sudo mkdir -p /var/log/goalstick
	@# Generate service file from template
	sed 's|__INSTALL_DIR__|$(INSTALL_DIR)|g' $(SERVICE_TEMPLATE) | sudo tee /etc/systemd/system/goalstick.service > /dev/null
	sudo systemctl daemon-reload
	sudo systemctl enable goalstick.service
	sudo systemctl start goalstick.service
	@echo "Service installed and started!"
	@echo "Config: /etc/goalstick/config.json"
	@echo "Logs:   /var/log/goalstick/goalstick.log"

service-uninstall:
	@echo "Removing GoalStick systemd service..."
	-sudo systemctl stop goalstick.service
	-sudo systemctl disable goalstick.service
	-sudo rm -f /etc/systemd/system/goalstick.service
	sudo systemctl daemon-reload
	@echo "Service removed!"
	@echo "Note: Config and logs preserved in /etc/goalstick and /var/log/goalstick"

service-status:
	@sudo systemctl status goalstick.service

service-logs:
	@sudo tail -f /var/log/goalstick/goalstick.log
