# Porting to an original Raspberry Pi Zero

Status: not started — this is a runbook for when it happens, written from
investigating the current deployment (a Pi 3 running 64-bit Debian 13
"trixie", `docs/deployment.md`) against the original Pi Zero's constraints.
Target hardware: original Pi Zero (single-core ARM11, ARMv6, 32-bit only,
512MB RAM, **no onboard networking**) + a USB OTG Ethernet adapter (already
on hand) for connectivity.

## Why this isn't a straight clone of the current setup

- **Architecture**: the current box runs 64-bit Debian (`aarch64`). Original
  Pi Zero's ARM11 core is ARMv6, 32-bit only — it cannot run `aarch64`
  binaries at all. Needs actual 32-bit Raspberry Pi OS, not this image.
- **No onboard WiFi/Bluetooth** (that's Zero *W* and later) — the OTG
  Ethernet adapter is the only way it reaches the MQTT broker, the Mac over
  SSH, and receives AirPlay traffic in the first place.
- **`cryptography` (a `paramiko` dependency) needs Rust to build from
  source** on platforms without a prebuilt wheel — and PyPI doesn't publish
  wheels for raw `armv6l`, only `armv7l`/`aarch64`. Building a Rust
  toolchain on a single ARM11 core with 512MB RAM is the single biggest
  practical risk in this whole port. **Not yet verified**: whether an older
  `cryptography` version (pre-Rust-requirement, roughly pre-3.4) is
  compatible with `paramiko==5.0.0` as currently pinned in
  `src/requirements.txt` — needs testing; may require pinning an older
  `paramiko` too, or just accepting the Rust build (slow but possible).

## Confirmed portable as-is (verified while investigating, not just assumed)

- `jukeboxPanelModule/` (the keypad kernel driver) uses the generic
  BCM-numbered `gpio_request()` API, not hardcoded memory addresses — same
  interface across the whole 40-pin Pi lineup. Just needs rebuilding
  against the Zero's own kernel headers.
- I2C/display code (`src/drivers/led16_display.py`) goes through Blinka's
  board-detection layer, not a hardcoded I2C bus number. Confirmed in
  `adafruit_platformdetect/revcodes.py`: "Zero" (`0x09`), "Zero W" (`0x0C`),
  and "Zero 2 W" (`0x12`) are all explicitly recognized revision codes.
- Nothing in the app depends on multiple cores — all the threading
  (MQTT/SSH/coordinator) is I/O-bound and cooperative.

## Steps

1. **Flash 32-bit Raspberry Pi OS** (Lite is fine, headless) — not this
   box's image. Enable SSH before first boot (`ssh` file on the boot
   partition, or `raspi-config`).
2. **Networking via the OTG Ethernet adapter** — should be picked up by the
   kernel's standard USB Ethernet (CDC-ECM/RNDIS) driver automatically;
   confirm with `ip addr` after boot. No GPIO/USB contention with the
   keypad or displays, since those are on the header, not USB.
3. **Enable I2C**: `sudo raspi-config nonint do_i2c 0`.
4. **Install build/runtime dependencies**:
   `sudo apt install -y git python3-venv python3-pip build-essential libssl-dev libffi-dev raspberrypi-kernel-headers i2c-tools`
5. **Clone the repo** and create the venv, but before installing
   `src/requirements.txt` as-is, resolve the `cryptography`/Rust question
   above (test whether an older pin avoids it; fall back to installing
   `rustup` and letting it build from source if not — budget real time for
   this, it's slow on this hardware).
6. **Rebuild and install the kernel module**:
   `cd jukeboxPanelModule && make && sudo make install` (installs to
   `/lib/modules/$(uname -r)/extra` + `depmod -a`, per the Makefile).
   While in there: fix `jukebox-panel.modules-load.conf`, which currently
   references `jukebox_panel` (the ASCII driver) — `config.ini`'s active
   selection is the *binary* driver, so it should say `jukebox_panel_bin`
   instead (a pre-existing inconsistency on the current box too, worth
   fixing regardless of this port).
7. **Wire the hardware** — same physical GPIO/I2C wiring as the current
   box; BCM pin numbering is consistent across the Pi lineup, see
   `jukeboxPanelModule/WIRING.md`.
8. **Adapt `src/config.ini`** for the new host: `[mqtt]` broker address
   (wherever it actually runs — locally on the Zero, or remote), `[sshWorker]`
   settings unchanged in shape but double-check paths.
9. **Decide where mosquitto/shairport-sync run** — either also on the Zero
   (shairport-sync is a well-established target for exactly this hardware)
   or left on the existing box, with the jukebox app on the Zero talking to
   them remotely.
10. **Adapt the systemd unit** (`systemd/jukebox.service`) — the
    `ProtectSystem=strict`/`ProtectHome=read-only`/volatile-journald
    approach from `docs/deployment.md` carries over unchanged; just update
    `User=`/paths for wherever the checkout actually lives on the Zero.
11. **Watch memory closely once everything's running together** — 512MB
    total, shared between the jukebox app, and possibly mosquitto and
    shairport-sync if they're colocated too. The jukebox app alone is tiny
    (~47MB RSS observed on the current box), but the combined footprint on
    a Zero hasn't been measured yet.

## Explicitly out of scope for this port

Running Claude Code itself on the Zero — Node.js dropped official `armv6l`
binaries years ago (only unofficial community builds exist), and even if
that worked, a single ARM11 core + 512MB is a poor fit for it alongside the
actual jukebox workload. Manage the Zero remotely over SSH from wherever
Claude Code already runs instead — the same pattern already used for the
Mac (`MusicAppSSHWorker`) and this Pi 3.
