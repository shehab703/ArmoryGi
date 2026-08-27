#!/bin/bash
# ArmoryGIS Pro Build Script
set -e

echo "🛡️  ArmoryGIS Pro Build Script"
echo "==============================="

# Configuration
APP_NAME="ArmoryGIS Pro"
VERSION="1.0.0"
OUTPUT_DIR="dist"
SPEC_FILE="packaging/pyinstaller.spec"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check dependencies
check_deps() {
    log_info "Checking dependencies..."
    
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 not found"
        exit 1
    fi
    
    if ! python3 -c "import PyQt6" &> /dev/null; then
        log_error "PyQt6 not installed. Run: pip install -r requirements.txt"
        exit 1
    fi
    
    if ! command -v pyinstaller &> /dev/null; then
        log_warn "PyInstaller not found, installing..."
        pip install pyinstaller
    fi
}

# Clean previous builds
clean_build() {
    log_info "Cleaning previous builds..."
    rm -rf build/ "$OUTPUT_DIR"/ *.spec~ 2>/dev/null || true
}

# Run tests
run_tests() {
    log_info "Running tests..."
    if [ -d "tests" ]; then
        python3 -m pytest tests/ -v --tb=short || log_warn "Tests failed, continuing build..."
    else
        log_warn "No tests directory found"
    fi
}

# Build with PyInstaller
build_app() {
    log_info "Building application with PyInstaller..."
    
    pyinstaller --clean "$SPEC_FILE"
    
    if [ $? -eq 0 ]; then
        log_info "✅ Build successful!"
        ls -lh "$OUTPUT_DIR"/
    else
        log_error "❌ Build failed"
        exit 1
    fi
}

# Create installer package (optional)
create_installer() {
    log_info "Creating installer package..."
    
    case "$(uname -s)" in
        Linux*)
            # Create AppImage (simplified)
            log_warn "AppImage creation requires appimagetool - skipping for now"
            ;;
        Darwin*)
            # Create DMG (requires create-dmg)
            if command -v create-dmg &> /dev/null; then
                create-dmg \
                    --volname "$APP_NAME" \
                    --window-pos 200 120 \
                    --window-size 600 400 \
                    --icon-size 100 \
                    --icon "$APP_NAME.app" 175 120 \
                    --hide-extension "$APP_NAME.app" \
                    --app-drop-link 425 120 \
                    "$OUTPUT_DIR/$APP_NAME-$VERSION.dmg" \
                    "$OUTPUT_DIR/$APP_NAME.app"
            else
                log_warn "create-dmg not found, skipping DMG creation"
            fi
            ;;
        CYGWIN*|MINGW*|MSYS*)
            log_info "Windows installer creation requires InnoSetup - skipping"
            ;;
    esac
}

# Main build process
main() {
    echo ""
    log_info "Starting build for $APP_NAME v$VERSION"
    echo ""
    
    check_deps
    clean_build
    run_tests
    build_app
    create_installer
    
    echo ""
    log_info "🎉 Build complete!"
    log_info "Executable location: $OUTPUT_DIR/"
    echo ""
}

# Run main
main "$@"