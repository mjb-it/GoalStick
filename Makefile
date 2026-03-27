# GoalStick Makefile
# Build and test targets for Android app and Python code

.PHONY: help android-build android-release android-clean android-install \
        python-venv python-check-venv python-test python-test-cov python-install python-clean \
        deploy deploy-readonly service-install service-uninstall service-status service-logs \
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
	@echo "Deployment targets (run on Pi):"
	@echo "  deploy           Deploy to /opt/goalstick and install service"
	@echo "  deploy-readonly  Deploy + set up read-only filesystem (reboot required)"
	@echo "  service-install  Install systemd service from current directory"
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

# =============================================================================
# Deployment Target
# =============================================================================

DEPLOY_DIR := /opt/goalstick

deploy:
	@echo "Deploying GoalStick to $(DEPLOY_DIR)..."
	@# Stop existing service if running
	-sudo systemctl stop goalstick.service 2>/dev/null || true
	@# Install system dependencies
	@echo "Installing system dependencies..."
	sudo apt-get update -qq
	sudo apt-get install -y python3-dev python3-dbus python3-rpi.gpio libdbus-1-dev bluez curl
	@# Install arduino-cli for ESP32 OTA updates
	@echo "Installing arduino-cli..."
	@if [ ! -f "/usr/local/bin/arduino-cli" ]; then \
		curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sudo BINDIR=/usr/local/bin sh; \
		sudo arduino-cli config init; \
		sudo arduino-cli config add board_manager.additional_urls https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json; \
		sudo arduino-cli core update-index; \
		sudo arduino-cli core install esp32:esp32; \
		sudo arduino-cli lib install "Adafruit NeoPixel"; \
		echo "arduino-cli installed and configured for ESP32"; \
	else \
		echo "arduino-cli already installed"; \
	fi
	@# Enable BlueZ compatibility mode for SDP (required for RFCOMM on modern BlueZ)
	@echo "Configuring Bluetooth for RFCOMM/SDP support..."
	@if ! grep -q '\-\-compat' /lib/systemd/system/bluetooth.service; then \
		sudo sed -i 's|ExecStart=/usr/libexec/bluetooth/bluetoothd|ExecStart=/usr/libexec/bluetooth/bluetoothd --compat|' /lib/systemd/system/bluetooth.service; \
		sudo systemctl daemon-reload; \
		sudo systemctl restart bluetooth; \
		echo "BlueZ --compat mode enabled"; \
	else \
		echo "BlueZ --compat mode already enabled"; \
	fi
	@# Disable Bluetooth Secure Connections to allow legacy SSP pairing with Android
	@echo "Configuring BlueZ policy (disabling Secure Connections)..."
	sudo mkdir -p /etc/bluetooth
	@printf '[Policy]\nSecureConnections = off\n' | sudo tee /etc/bluetooth/main.conf > /dev/null
	sudo systemctl restart bluetooth
	@echo "BlueZ policy configured"
	@# Create deploy directory
	sudo mkdir -p $(DEPLOY_DIR)
	@# Copy Python source (excluding __pycache__, .pyc, etc.)
	sudo rsync -av --delete \
		--exclude='__pycache__' \
		--exclude='*.pyc' \
		--exclude='*.egg-info' \
		--exclude='.pytest_cache' \
		$(PYTHON_DIR)/ $(DEPLOY_DIR)/PythonSrc/
	@# Copy team colors data
	@if [ -d "data" ]; then sudo rsync -av data/ $(DEPLOY_DIR)/data/; fi
	@# Copy ESP32 source for OTA updates
	sudo rsync -av ESP32/ $(DEPLOY_DIR)/ESP32/
	@# Copy .git for auto-updates
	sudo rsync -av .git/ $(DEPLOY_DIR)/.git/
	@# Mark directory as safe for git (needed for auto-updates when running as root)
	sudo git config --global --add safe.directory $(DEPLOY_DIR)
	@# Create virtual environment if needed
	@if [ ! -d "$(DEPLOY_DIR)/.venv" ]; then \
		echo "Creating virtual environment..."; \
		sudo python3 -m venv $(DEPLOY_DIR)/.venv --system-site-packages; \
	fi
	@# Install package with rpi extras (includes dbus-python, RPi.GPIO)
	sudo $(DEPLOY_DIR)/.venv/bin/pip install -e "$(DEPLOY_DIR)/PythonSrc[rpi]"
	@# Create config and log directories
	sudo mkdir -p /etc/goalstick
	sudo mkdir -p /var/log/goalstick
	@# Install service
	sed 's|__INSTALL_DIR__|$(DEPLOY_DIR)|g' $(SERVICE_TEMPLATE) | sudo tee /etc/systemd/system/goalstick.service > /dev/null
	sudo systemctl daemon-reload
	sudo systemctl enable goalstick.service
	sudo systemctl start goalstick.service
	@# Copy setup scripts
	sudo mkdir -p $(DEPLOY_DIR)/scripts
	sudo cp scripts/setup-readonly.sh $(DEPLOY_DIR)/scripts/ 2>/dev/null || true
	sudo chmod +x $(DEPLOY_DIR)/scripts/*.sh 2>/dev/null || true
	@echo ""
	@echo "Deployment complete!"
	@echo "  Install dir: $(DEPLOY_DIR)"
	@echo "  Config:      /etc/goalstick/config.json"
	@echo "  Logs:        /var/log/goalstick/goalstick.log"
	@echo ""
	@echo "Commands:"
	@echo "  make service-status  - Check service status"
	@echo "  make service-logs    - View logs"
	@echo "  make deploy-readonly - Enable read-only filesystem (optional)"

deploy-readonly: deploy
	@echo ""
	@echo "Setting up read-only filesystem..."
	@if [ -f "$(DEPLOY_DIR)/scripts/setup-readonly.sh" ]; then \
		sudo $(DEPLOY_DIR)/scripts/setup-readonly.sh; \
	else \
		echo "Error: setup-readonly.sh not found"; \
		exit 1; \
	fi
