# GoalStick Makefile
# Build and test targets for Android app and Python code

.PHONY: help android-build android-release android-clean android-install \
        python-test python-test-cov python-install python-clean \
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
	@echo "  python-test      Run Python unit tests"
	@echo "  python-test-cov  Run tests with coverage report"
	@echo "  python-install   Install Python package in dev mode"
	@echo "  python-clean     Clean Python build artifacts"
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

android-build:
	@echo "Building Android debug APK..."
	cd $(ANDROID_DIR) && ./gradlew assembleDebug
	@echo "APK: $(ANDROID_DIR)/app/build/outputs/apk/debug/app-debug.apk"

android-release:
	@echo "Building Android release APK..."
	cd $(ANDROID_DIR) && ./gradlew assembleRelease
	@echo "APK: $(ANDROID_DIR)/app/build/outputs/apk/release/app-release.apk"

android-install: android-build
	@echo "Installing APK to connected device..."
	adb install -r $(ANDROID_DIR)/app/build/outputs/apk/debug/app-debug.apk

android-clean:
	@echo "Cleaning Android build..."
	cd $(ANDROID_DIR) && ./gradlew clean
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

python-test:
	@echo "Running Python tests..."
	cd $(PYTHON_DIR) && ../$(PYTEST) -v

python-test-cov:
	@echo "Running Python tests with coverage..."
	cd $(PYTHON_DIR) && ../$(PYTEST) --cov=StickCheck --cov-report=term-missing

python-install:
	@echo "Installing Python package in dev mode..."
	cd $(PYTHON_DIR) && ../$(PIP) install -e ".[dev]"

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
