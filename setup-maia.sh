#!/bin/bash
# ============================================================================
# Maia Setup Script
# ============================================================================
# Quick setup for developers who cloned the repo manually.
# Uses uv for desktop/server setup and Python's stdlib venv + pip on Termux.
#
# Usage:
#   ./setup-maia.sh
#
# This script:
# 1. Detects desktop/server vs Android/Termux setup path
# 2. Creates a Python 3.11 virtual environment
# 3. Installs the appropriate dependency set for the platform
# 4. Creates .env from template (if not exists)
# 5. Symlinks the 'maia' CLI command into a user-facing bin dir
# 6. Runs the setup wizard (optional)
# ============================================================================

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_VERSION="3.11"

is_termux() {
    [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux/files/usr"* ]]
}

is_wsl() {
    grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null
}

# WSL note: /mnt/<drive> is the NTFS bridge — installs there are slow, break
# hardlinks (uv cache lives on the Linux filesystem), and are the most common
# source of flaky Windows installs. Recommend the Linux filesystem and switch
# uv to copy-mode links so it doesn't spam degraded-performance warnings.
if is_wsl; then
    case "$SCRIPT_DIR" in
        /mnt/*)
            echo ""
            echo -e "${YELLOW}⚠ You are installing from the Windows filesystem ($SCRIPT_DIR).${NC}"
            echo "  WSL is much faster and more reliable on the Linux filesystem."
            echo "  Recommended: clone into your WSL home instead:"
            echo "    git clone https://github.com/and270/maia.git ~/maia"
            echo "    cd ~/maia && ./setup-maia.sh"
            echo ""
            export UV_LINK_MODE="${UV_LINK_MODE:-copy}"
            ;;
    esac
fi

path_has_dir() {
    echo "$PATH" | tr ':' '\n' | grep -Fxq "$1"
}

ensure_writable_dir() {
    mkdir -p "$1" 2>/dev/null && [ -w "$1" ]
}

get_uv_install_dir() {
    local preferred_dir="$HOME/.local/bin"
    local fallback_dir="$HOME/.maia/bin"

    if ensure_writable_dir "$preferred_dir"; then
        echo "$preferred_dir"
    else
        mkdir -p "$fallback_dir"
        echo "$fallback_dir"
    fi
}

get_command_link_dir() {
    if is_termux && [ -n "${PREFIX:-}" ]; then
        echo "$PREFIX/bin"
    else
        local preferred_dir="$HOME/.local/bin"
        local fallback_dir="$HOME/.maia/bin"

        if ensure_writable_dir "$preferred_dir"; then
            echo "$preferred_dir"
            return
        fi

        # Prefer conventional writable bin dirs already on PATH so
        # `maia setup` works immediately after this script exits.
        for path_dir in "$HOME/bin" "$HOME/.maia/bin" "/opt/homebrew/bin" "/usr/local/bin"; do
            if path_has_dir "$path_dir" && ensure_writable_dir "$path_dir"; then
                echo "$path_dir"
                return
            fi
        done

        mkdir -p "$fallback_dir"
        echo "$fallback_dir"
    fi
}

get_command_link_display_dir() {
    local resolved_dir="${1:-}"

    if is_termux && [ -n "${PREFIX:-}" ]; then
        echo '$PREFIX/bin'
    elif [ "$resolved_dir" = "$HOME/.local/bin" ]; then
        echo '~/.local/bin'
    elif [ "$resolved_dir" = "$HOME/.maia/bin" ]; then
        echo '~/.maia/bin'
    elif [[ "$resolved_dir" == "$HOME/"* ]]; then
        echo "~/${resolved_dir#$HOME/}"
    else
        echo "$resolved_dir"
    fi
}

echo ""
echo -e "${CYAN}Maia Setup${NC}"
echo ""

# ============================================================================
# Install / locate uv
# ============================================================================

echo -e "${CYAN}→${NC} Checking for uv..."

UV_CMD=""
if is_termux; then
    echo -e "${CYAN}→${NC} Termux detected — using Python's stdlib venv + pip instead of uv"
else
    if command -v uv &> /dev/null; then
        UV_CMD="uv"
    elif [ -x "$HOME/.local/bin/uv" ]; then
        UV_CMD="$HOME/.local/bin/uv"
    elif [ -x "$HOME/.maia/bin/uv" ]; then
        UV_CMD="$HOME/.maia/bin/uv"
    elif [ -x "$HOME/.cargo/bin/uv" ]; then
        UV_CMD="$HOME/.cargo/bin/uv"
    fi

    if [ -n "$UV_CMD" ]; then
        UV_VERSION=$($UV_CMD --version 2>/dev/null)
        echo -e "${GREEN}✓${NC} uv found ($UV_VERSION)"
    else
        echo -e "${CYAN}→${NC} Installing uv..."
        UV_INSTALL_DIR="$(get_uv_install_dir)"
        UV_INSTALL_DISPLAY_DIR="$(get_command_link_display_dir "$UV_INSTALL_DIR")"
        if [ "$UV_INSTALL_DIR" != "$HOME/.local/bin" ]; then
            echo -e "${YELLOW}⚠${NC} ~/.local/bin is not writable; installing uv to $UV_INSTALL_DISPLAY_DIR"
        fi

        if curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR="$UV_INSTALL_DIR" sh 2>/dev/null; then
            if [ -x "$UV_INSTALL_DIR/uv" ]; then
                UV_CMD="$UV_INSTALL_DIR/uv"
            elif [ -x "$HOME/.local/bin/uv" ]; then
                UV_CMD="$HOME/.local/bin/uv"
            elif [ -x "$HOME/.maia/bin/uv" ]; then
                UV_CMD="$HOME/.maia/bin/uv"
            elif [ -x "$HOME/.cargo/bin/uv" ]; then
                UV_CMD="$HOME/.cargo/bin/uv"
            fi

            if [ -n "$UV_CMD" ]; then
                UV_VERSION=$($UV_CMD --version 2>/dev/null)
                echo -e "${GREEN}✓${NC} uv installed ($UV_VERSION)"
            else
                echo -e "${RED}✗${NC} uv installed but not found. Add $UV_INSTALL_DISPLAY_DIR to PATH and retry."
                exit 1
            fi
        else
            echo -e "${RED}✗${NC} Failed to install uv. Visit https://docs.astral.sh/uv/"
            exit 1
        fi
    fi
fi

# ============================================================================
# Python check (uv can provision it automatically)
# ============================================================================

echo -e "${CYAN}→${NC} Checking Python $PYTHON_VERSION..."

if is_termux; then
    if command -v python >/dev/null 2>&1; then
        PYTHON_PATH="$(command -v python)"
        if "$PYTHON_PATH" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            PYTHON_FOUND_VERSION=$($PYTHON_PATH --version 2>/dev/null)
            echo -e "${GREEN}✓${NC} $PYTHON_FOUND_VERSION found"
        else
            echo -e "${RED}✗${NC} Termux Python must be 3.11+"
            echo "    Run: pkg install python"
            exit 1
        fi
    else
        echo -e "${RED}✗${NC} Python not found in Termux"
        echo "    Run: pkg install python"
        exit 1
    fi
else
    if $UV_CMD python find "$PYTHON_VERSION" &> /dev/null; then
        PYTHON_PATH=$($UV_CMD python find "$PYTHON_VERSION")
        PYTHON_FOUND_VERSION=$($PYTHON_PATH --version 2>/dev/null)
        echo -e "${GREEN}✓${NC} $PYTHON_FOUND_VERSION found"
    else
        echo -e "${CYAN}→${NC} Python $PYTHON_VERSION not found, installing via uv..."
        $UV_CMD python install "$PYTHON_VERSION"
        PYTHON_PATH=$($UV_CMD python find "$PYTHON_VERSION")
        PYTHON_FOUND_VERSION=$($PYTHON_PATH --version 2>/dev/null)
        echo -e "${GREEN}✓${NC} $PYTHON_FOUND_VERSION installed"
    fi
fi

# ============================================================================
# Virtual environment
# ============================================================================

echo -e "${CYAN}→${NC} Setting up virtual environment..."

if [ -d "venv" ]; then
    echo -e "${CYAN}→${NC} Removing old venv..."
    rm -rf venv
fi

if is_termux; then
    "$PYTHON_PATH" -m venv venv
    echo -e "${GREEN}✓${NC} venv created with stdlib venv"
else
    $UV_CMD venv venv --python "$PYTHON_VERSION"
    echo -e "${GREEN}✓${NC} venv created (Python $PYTHON_VERSION)"
fi

export VIRTUAL_ENV="$SCRIPT_DIR/venv"
SETUP_PYTHON="$SCRIPT_DIR/venv/bin/python"

# ============================================================================
# Dependencies
# ============================================================================

echo -e "${CYAN}→${NC} Installing dependencies..."

if is_termux; then
    export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk 2>/dev/null || printf '%s' "${ANDROID_API_LEVEL:-}")"
    echo -e "${CYAN}→${NC} Termux detected — installing the tested Android bundle"
    "$SETUP_PYTHON" -m pip install --upgrade pip setuptools wheel
    if [ -f "constraints-termux.txt" ]; then
        "$SETUP_PYTHON" -m pip install -e ".[termux]" -c constraints-termux.txt || {
            echo -e "${YELLOW}⚠${NC} Termux bundle install failed, falling back to base install..."
            "$SETUP_PYTHON" -m pip install -e "." -c constraints-termux.txt
        }
    else
        "$SETUP_PYTHON" -m pip install -e ".[termux]" || "$SETUP_PYTHON" -m pip install -e "."
    fi
    echo -e "${GREEN}✓${NC} Dependencies installed"
else
    install_failed() {
        echo ""
        echo -e "${RED}✗ Dependency installation failed.${NC}"
        echo "  Nothing was launched because the install is incomplete."
        echo "  Common causes and fixes:"
        echo "    - Flaky network: re-run  ./setup-maia.sh"
        if is_wsl; then
            echo "    - Windows filesystem (/mnt/...): clone into your WSL home (~) and re-run"
        fi
        echo "    - Inspect the error above, then install manually:"
        echo "        source venv/bin/activate && uv pip install -e '.[all]'"
        exit 1
    }

    # Prefer uv sync with lockfile (hash-verified installs) when available,
    # fall back to pip install for compatibility or when lockfile is stale.
    if [ -f "uv.lock" ]; then
        echo -e "${CYAN}→${NC} Using uv.lock for hash-verified installation..."
        UV_SYNC_LOG="$(mktemp 2>/dev/null || echo /tmp/maia-uv-sync.log)"
        if UV_PROJECT_ENVIRONMENT="$SCRIPT_DIR/venv" $UV_CMD sync --all-extras --locked 2>"$UV_SYNC_LOG"; then
            echo -e "${GREEN}✓${NC} Dependencies installed (lockfile verified)"
        else
            echo -e "${YELLOW}⚠${NC} Lockfile install failed, falling back to pip install..."
            echo "  Reason (last lines from uv):"
            tail -n 6 "$UV_SYNC_LOG" 2>/dev/null | sed 's/^/    /'
            $UV_CMD pip install -e ".[all]" || $UV_CMD pip install -e "." || install_failed
            echo -e "${GREEN}✓${NC} Dependencies installed"
        fi
        rm -f "$UV_SYNC_LOG" 2>/dev/null || true
    else
        $UV_CMD pip install -e ".[all]" || $UV_CMD pip install -e "." || install_failed
        echo -e "${GREEN}✓${NC} Dependencies installed"
    fi

    # Sanity check: a core import must work before we advertise success or
    # offer the wizard. Catches silent partial installs (seen on WSL /mnt/*)
    # that otherwise crash later with ModuleNotFoundError.
    if ! "$SETUP_PYTHON" -c "import dotenv, httpx" 2>/dev/null; then
        echo -e "${RED}✗${NC} Core dependencies did not import after install."
        install_failed
    fi
fi

# ============================================================================
# Submodules (terminal backend + RL training)
# ============================================================================

echo -e "${CYAN}→${NC} Installing optional submodules..."

# tinker-atropos (RL training backend)
if is_termux; then
    echo -e "${CYAN}→${NC} Skipping tinker-atropos on Termux (not part of the tested Android path)"
elif [ -d "tinker-atropos" ] && [ -f "tinker-atropos/pyproject.toml" ]; then
    $UV_CMD pip install -e "./tinker-atropos" && \
        echo -e "${GREEN}✓${NC} tinker-atropos installed" || \
        echo -e "${YELLOW}⚠${NC} tinker-atropos install failed (RL tools may not work)"
else
    echo -e "${YELLOW}⚠${NC} tinker-atropos not found (run: git submodule update --init --recursive)"
fi

# ============================================================================
# Optional: ripgrep (for faster file search)
# ============================================================================

echo -e "${CYAN}→${NC} Checking ripgrep (optional, for faster search)..."

if command -v rg &> /dev/null; then
    echo -e "${GREEN}✓${NC} ripgrep found"
else
    echo -e "${YELLOW}⚠${NC} ripgrep not found (file search will use grep fallback)"
    read -p "Install ripgrep for faster search? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        INSTALLED=false

        if is_termux; then
            pkg install -y ripgrep && INSTALLED=true
        else
            # Check if sudo is available
            if command -v sudo &> /dev/null && sudo -n true 2>/dev/null; then
                if command -v apt &> /dev/null; then
                    sudo apt install -y ripgrep && INSTALLED=true
                elif command -v dnf &> /dev/null; then
                    sudo dnf install -y ripgrep && INSTALLED=true
                fi
            fi

            # Try brew (no sudo needed)
            if [ "$INSTALLED" = false ] && command -v brew &> /dev/null; then
                brew install ripgrep && INSTALLED=true
            fi

            # Try cargo (no sudo needed)
            if [ "$INSTALLED" = false ] && command -v cargo &> /dev/null; then
                echo -e "${CYAN}→${NC} Trying cargo install (no sudo required)..."
                cargo install ripgrep && INSTALLED=true
            fi
        fi

        if [ "$INSTALLED" = true ]; then
            echo -e "${GREEN}✓${NC} ripgrep installed"
        else
            echo -e "${YELLOW}⚠${NC} Auto-install failed. Install options:"
            if is_termux; then
                echo "    pkg install ripgrep          # Termux / Android"
            else
                echo "    sudo apt install ripgrep     # Debian/Ubuntu"
                echo "    brew install ripgrep         # macOS"
                echo "    cargo install ripgrep        # With Rust (no sudo)"
            fi
            echo "    https://github.com/BurntSushi/ripgrep#installation"
        fi
    fi
fi

# ============================================================================
# Dashboard frontend
# ============================================================================

echo -e "${CYAN}→${NC} Building dashboard frontend..."

if [ -f "web/package.json" ]; then
    NODE_BOOTSTRAP="$SCRIPT_DIR/scripts/lib/node-bootstrap.sh"
    if ! command -v npm >/dev/null 2>&1 && [ -f "$NODE_BOOTSTRAP" ]; then
        # shellcheck source=/dev/null
        if . "$NODE_BOOTSTRAP" && ensure_node; then
            :
        else
            echo -e "${YELLOW}⚠${NC} Node.js is not available; dashboard frontend was not built"
            echo "    Install Node.js, then run: cd web && npm install && npm run build"
        fi
    fi

    if command -v npm >/dev/null 2>&1; then
        (
            cd web
            if [ -f package-lock.json ]; then
                npm ci --silent || npm install --silent
            else
                npm install --silent
            fi
            npm run build
        ) && \
            echo -e "${GREEN}✓${NC} Dashboard frontend built" || {
            echo -e "${YELLOW}⚠${NC} Dashboard frontend build failed"
            echo "    Run manually: cd web && npm install && npm run build"
        }
    fi
else
    echo -e "${YELLOW}⚠${NC} web/package.json not found; skipping dashboard frontend"
fi

# ============================================================================
# Environment file
# ============================================================================

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${GREEN}✓${NC} Created .env from template"
    fi
else
    echo -e "${GREEN}✓${NC} .env exists"
fi

# ============================================================================
# PATH setup — symlink maia into a user-facing bin dir
# ============================================================================

echo -e "${CYAN}→${NC} Setting up maia command..."

MAIA_BIN="$SCRIPT_DIR/venv/bin/maia"
COMMAND_LINK_DIR="$(get_command_link_dir)"
COMMAND_LINK_DISPLAY_DIR="$(get_command_link_display_dir "$COMMAND_LINK_DIR")"
mkdir -p "$COMMAND_LINK_DIR"
ln -sf "$MAIA_BIN" "$COMMAND_LINK_DIR/maia"
ln -sf "$MAIA_BIN" "$COMMAND_LINK_DIR/coorporate"
echo -e "${GREEN}✓${NC} Symlinked maia -> $COMMAND_LINK_DISPLAY_DIR/maia"
echo -e "${GREEN}✓${NC} Legacy alias coorporate -> $COMMAND_LINK_DISPLAY_DIR/coorporate"

if is_termux; then
    export PATH="$COMMAND_LINK_DIR:$PATH"
    echo -e "${GREEN}✓${NC} $COMMAND_LINK_DISPLAY_DIR is already on PATH in Termux"
else
    # Determine the appropriate shell config file
    SHELL_CONFIG=""
    if [[ "$SHELL" == *"zsh"* ]]; then
        SHELL_CONFIG="$HOME/.zshrc"
    elif [[ "$SHELL" == *"bash"* ]]; then
        SHELL_CONFIG="$HOME/.bashrc"
        [ ! -f "$SHELL_CONFIG" ] && SHELL_CONFIG="$HOME/.bash_profile"
    else
        # Fallback to checking existing files
        if [ -f "$HOME/.zshrc" ]; then
            SHELL_CONFIG="$HOME/.zshrc"
        elif [ -f "$HOME/.bashrc" ]; then
            SHELL_CONFIG="$HOME/.bashrc"
        elif [ -f "$HOME/.bash_profile" ]; then
            SHELL_CONFIG="$HOME/.bash_profile"
        fi
    fi

    if [ -n "$SHELL_CONFIG" ]; then
        # Touch the file just in case it doesn't exist yet but was selected
        touch "$SHELL_CONFIG" 2>/dev/null || true

        PATH_EXPORT_DIR="$COMMAND_LINK_DIR"
        if [[ "$COMMAND_LINK_DIR" == "$HOME/"* ]]; then
            PATH_EXPORT_DIR="\$HOME/${COMMAND_LINK_DIR#$HOME/}"
        fi

        if ! path_has_dir "$COMMAND_LINK_DIR"; then
            if ! grep -Fq "$COMMAND_LINK_DIR" "$SHELL_CONFIG" 2>/dev/null && \
               ! grep -Fq "$PATH_EXPORT_DIR" "$SHELL_CONFIG" 2>/dev/null; then
                echo "" >> "$SHELL_CONFIG"
                echo "# Maia - ensure $COMMAND_LINK_DISPLAY_DIR is on PATH" >> "$SHELL_CONFIG"
                echo "export PATH=\"$PATH_EXPORT_DIR:\$PATH\"" >> "$SHELL_CONFIG"
                echo -e "${GREEN}✓${NC} Added $COMMAND_LINK_DISPLAY_DIR to PATH in $SHELL_CONFIG"
            else
                echo -e "${GREEN}✓${NC} $COMMAND_LINK_DISPLAY_DIR already in $SHELL_CONFIG"
            fi
        else
            echo -e "${GREEN}✓${NC} $COMMAND_LINK_DISPLAY_DIR already on PATH"
        fi
    fi
fi

# ============================================================================
# Seed bundled skills into Maia data home
# ============================================================================

MAIA_DATA_HOME="${MAIA_HOME:-${HERMES_HOME:-$HOME/.maia}}"
MAIA_SKILLS_DIR="$MAIA_DATA_HOME/skills"
mkdir -p "$MAIA_SKILLS_DIR"

echo ""
echo "Syncing bundled skills to $MAIA_DATA_HOME/skills/ ..."
if "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/tools/skills_sync.py" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Skills synced"
else
    # Fallback: copy if sync script fails (missing deps, etc.)
    if [ -d "$SCRIPT_DIR/skills" ]; then
        cp -rn "$SCRIPT_DIR/skills/"* "$MAIA_SKILLS_DIR/" 2>/dev/null || true
        echo -e "${GREEN}✓${NC} Skills copied"
    fi
fi

# ============================================================================
# Done
# ============================================================================

echo ""
echo -e "${GREEN}✓ Setup complete!${NC}"
echo ""
echo "Next steps:"
echo ""
if is_termux; then
    echo "  1. Run the setup wizard to configure API keys:"
    echo "     maia setup"
    echo ""
    echo "  2. Start chatting:"
    echo "     maia"
    echo ""
else
    echo "  1. Reload your shell:"
    echo "     source $SHELL_CONFIG"
    echo ""
    echo "  2. Run the setup wizard to configure API keys:"
    echo "     maia setup"
    echo ""
    echo "  3. Start chatting:"
    echo "     maia"
    echo ""
fi
echo "Other commands:"
echo "  maia status        # Check configuration"
if is_termux; then
    echo "  maia gateway       # Run gateway in foreground"
else
    echo "  maia gateway install # Install gateway service (messaging + cron)"
fi
echo "  maia cron list     # View scheduled jobs"
echo "  maia doctor        # Diagnose issues"
echo ""

# Ask if they want to run setup wizard now
read -p "Would you like to run the setup wizard now? [Y/n] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    echo ""
    # Run directly with venv Python (no activation needed)
    "$SCRIPT_DIR/venv/bin/python" -m hermes_cli.main setup
fi
