---
sidebar_position: 2
title: "Installation"
description: "Install Maia on Linux, macOS, WSL2, or Android via Termux"
---

# Installation

Get Maia up and running in under two minutes with the one-line installer.

## Quick Install

### Linux / macOS / WSL2

```bash
curl -fsSL https://ampliia.com/maia/install.sh | bash
```

### Android / Termux

Maia ships a Termux-aware installer path too:

```bash
git clone https://github.com/and270/maia.git
cd maia
./setup-maia.sh
```

The installer detects Termux automatically and switches to a tested Android flow:
- uses Termux `pkg` for system dependencies (`git`, `python`, `nodejs`, `ripgrep`, `ffmpeg`, build tools)
- creates the virtualenv with `python -m venv`
- exports `ANDROID_API_LEVEL` automatically for Android wheel builds
- installs a curated `.[termux]` extra with `pip`
- skips the untested browser / WhatsApp bootstrap by default

If you want the fully explicit path, follow the dedicated [Termux guide](./termux.md).

:::warning Windows
Native Windows is **not supported**. Please install [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) and run Maia from there. The install command above works inside WSL2.
:::

### What the Installer Does

The installer handles everything automatically — dependencies (Python, Node.js, ripgrep, ffmpeg), the repo clone, virtual environment, the `maia` command, and guided provider configuration. It prefers `~/.local/bin` for user commands. If that directory is unavailable or not writable, it automatically uses `~/.maia/bin` and updates the shell PATH instead.

#### Install Layout

Where the installer puts things depends on whether you're installing as a normal user or as root:

| Installer | Code lives at | `maia` launcher | Data directory |
|---|---|---|---|
| Per-user (normal) | `~/.maia/maia/` | `~/.local/bin/maia`, or `~/.maia/bin/maia` when needed | `~/.maia/` |
| Linux root-mode | `/usr/local/lib/maia/` | `/usr/local/bin/maia` | `/root/.maia/` (or `$MAIA_HOME`) |

The root-mode **FHS layout** (`/usr/local/lib/maia`, `/usr/local/bin/maia`) is Linux-only and matches where other system-wide developer tools land. Normal macOS, Linux, and WSL installs remain user-scoped and do not need `sudo`.

### After Installation

Reload your shell and start chatting:

```bash
source ~/.bashrc   # or: source ~/.zshrc
maia               # Open Maia
```

To reconfigure individual settings later, use the dedicated commands:

```bash
maia model          # Choose your LLM provider and model
maia tools          # Configure which tools are enabled
maia gateway setup  # Set up messaging platforms
maia config set     # Set individual config values
maia setup          # Or run the full setup wizard to configure everything at once
```

---

## Prerequisites

The only prerequisite is **Git**. The installer automatically handles everything else:

- **uv** (fast Python package manager)
- **Python 3.11** (via uv, no sudo needed)
- **Node.js v22** (for browser automation and WhatsApp bridge)
- **ripgrep** (fast file search)
- **ffmpeg** (audio format conversion for TTS)

:::info
You do **not** need to install Python, Node.js, ripgrep, or ffmpeg manually. The installer detects what's missing and installs it for you. Just make sure `git` is available (`git --version`).
:::

:::tip Nix users
If you use Nix (on NixOS, macOS, or Linux), there's a dedicated setup path with a Nix flake, declarative NixOS module, and optional container mode. See the **[Nix & NixOS Setup](./nix-setup.md)** guide.
:::

---

## Manual / Developer Installation

If you want to clone the repo and install from source — for contributing, running from a specific branch, or having full control over the virtual environment — see the [Development Setup](../developer-guide/contributing.md#development-setup) section in the Contributing guide.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `maia: command not found` | Reload your shell (`source ~/.bashrc` or `source ~/.zshrc`) and check `~/.local/bin` or `~/.maia/bin` in PATH |
| `API key not set` | Run `maia model` to configure your provider, or `maia config set OPENROUTER_API_KEY your_key` |
| Missing config after update | Run `maia config check` then `maia config migrate` |

For more diagnostics, run `maia doctor` — it will tell you exactly what's missing and how to fix it.
