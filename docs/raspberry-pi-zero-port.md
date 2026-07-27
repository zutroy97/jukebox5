# Porting to an original Raspberry Pi Zero

Status: **hardware/dependency layer verified working, panel keypad and
alpha displays not physically wired up yet.** Device is up as `jukebox0`,
reachable over SSH (via the OTG Ethernet adapter), with passwordless
SSH+sudo for `simonbs`. Target hardware: original Pi Zero (single-core
ARM11, ARMv6, 32-bit only, 512MB RAM, no onboard networking) + a USB OTG
Ethernet adapter for connectivity. Actual OS: Raspbian (32-bit, trixie),
kernel `6.18.33+rpt-rpi-v6`.

## Why this isn't a straight clone of the current setup

- **Architecture**: the Pi 3 box (`docs/deployment.md`) runs 64-bit Debian
  (`aarch64`). Original Pi Zero's ARM11 core is ARMv6, 32-bit only — it
  cannot run `aarch64` binaries at all. Needed actual 32-bit Raspberry Pi
  OS (Raspbian), not that image — confirmed this is what's actually
  installed on `jukebox0`.
- **No onboard WiFi/Bluetooth** (that's Zero *W* and later) — the OTG
  Ethernet adapter is how it reaches the MQTT broker, the Mac over SSH, and
  would receive AirPlay traffic. (A USB WiFi dongle also showed up
  associating in `dmesg` on this particular unit — so it may have both;
  either way, networking is confirmed working, real internet access
  included — apt/pip/GitHub all reachable.)
- **`cryptography` (a `paramiko` dependency) risk — resolved, not just
  theorized.** The concern was that it needs Rust to build from source
  without a prebuilt wheel, and PyPI doesn't publish `armv6l` wheels.
  **Verified this isn't a problem**: Raspbian ships with `piwheels.org`
  preconfigured as an extra pip index (`/etc/pip.conf`), and it *does*
  publish prebuilt `linux_armv6l` wheels for `cryptography`, `cffi`,
  `bcrypt`, and `pynacl` — confirmed by actually installing the pinned
  `src/requirements.txt` (`paramiko==5.0.0` included) on `jukebox0`: every
  package installed from a wheel, zero source compilation, ~2m43s total
  (nearly all of it network download time on a slow link, not CPU). No
  Rust toolchain needed at all.

## Confirmed portable/working (verified directly on jukebox0, not just assumed)

- `jukeboxPanelModule/` (the keypad kernel driver) uses the generic
  BCM-numbered `gpio_request()` API, not hardcoded memory addresses — same
  interface across the whole 40-pin Pi lineup. Built clean with `make`
  against the already-installed matching kernel headers (no extra headers
  package needed — see step 4), installed with `sudo make install`,
  loaded with `modprobe jukebox_panel_bin`, registered
  `/dev/jukebox_panel_bin` correctly (confirmed in `dmesg`), and opened
  successfully as `simonbs` once the udev rule/group were in place.
- I2C/display code (`src/drivers/led16_display.py`) goes through Blinka's
  board-detection layer, not a hardcoded I2C bus number. Confirmed in
  `adafruit_platformdetect/revcodes.py`: "Zero" (`0x09`), "Zero W" (`0x0C`),
  and "Zero 2 W" (`0x12`) are all explicitly recognized revision codes.
  (Not yet tested against real hardware — displays aren't wired up yet.)
- Nothing in the app depends on multiple cores — all the threading
  (MQTT/SSH/coordinator) is I/O-bound and cooperative.
- Python: `jukebox0` already has Python 3.13.5 via apt — same version as
  the Pi 3 box, no version-pin adjustment needed after all.

## Steps

1. ✅ **Flash 32-bit Raspberry Pi OS** (Raspbian, headless) — done. Hostname
   `jukebox0`, SSH key auth set up for `simonbs` (both direct from `jukebox4`
   and via `mbp2017`), passwordless sudo granted.
2. ✅ **Networking via the OTG Ethernet adapter** — done, confirmed working
   (apt/pip/GitHub all reachable; also saw a USB WiFi dongle associate in
   `dmesg` on this unit, so it may have two paths).
3. ✅ **Enable I2C**: `sudo raspi-config nonint do_i2c 0` — done.
4. ✅ **Install build/runtime dependencies** — done:
   `sudo apt install -y git python3-venv python3-pip build-essential libssl-dev libffi-dev i2c-tools`
   (no separate kernel-headers package needed — `linux-headers-6.18.33+rpt-rpi-v6`
   matching the running kernel was already installed on this image; the
   `raspberrypi-kernel-headers` package name from the original plan doesn't
   exist on this OS release).
5. ✅ **Clone the repo**, create the venv, install `src/requirements.txt` —
   done, all packages via prebuilt wheels (see above), verified core imports
   (`paramiko`, `paho.mqtt`, `busio`/`board`, `adafruit_ht16k33`) all work.
6. ✅ **Rebuild and install the kernel module** — done:
   `cd jukeboxPanelModule && make && sudo make install`, then
   `sudo cp 99-jukebox-panel.rules /etc/udev/rules.d/` +
   `echo jukebox_panel_bin | sudo tee /etc/modules-load.d/jukebox-panel.conf`.
   Also fixed `jukebox-panel.modules-load.conf` in the repo itself, which
   referenced `jukebox_panel` (the ASCII driver) instead of the binary
   driver `config.ini` actually selects — a real bug, not Zero-specific,
   now corrected at the source. Confirmed: module loads, registers
   `/dev/jukebox_panel_bin`, owned `root:gpio` 660 after the udev rule
   applied (needed a module reload to take effect on an already-loaded
   module — reapply-on-trigger alone didn't retroactively fix an existing
   device node's ownership), opens successfully as `simonbs`.
7. ⬜ **Wire the hardware** — not done yet. Panel keypad and alpha displays
   not physically connected. Same physical GPIO/I2C wiring as the Pi 3 box
   applies; BCM pin numbering is consistent across the Pi lineup, see
   `jukeboxPanelModule/WIRING.md`.
8. ⬜ **Adapt `src/config.ini`** for the new host — not done yet: `[mqtt]`
   broker address (wherever it actually runs — locally on the Zero, or
   remote), `[sshWorker]` settings unchanged in shape but double-check paths.
9. ⬜ **Decide where mosquitto/shairport-sync run** — not decided yet:
   either also on the Zero (shairport-sync is a well-established target for
   exactly this hardware) or left on the existing box, with the jukebox app
   on the Zero talking to them remotely.
10. ⬜ **Adapt the systemd unit** (`systemd/jukebox.service`) — not done
    yet. The `ProtectSystem=strict`/`ProtectHome=read-only`/
    volatile-journald approach from `docs/deployment.md` should carry over
    unchanged; just needs `User=`/paths updated for wherever the checkout
    lives on the Zero (currently `/home/simonbs/jukebox5`, matches the Pi 3
    layout).
11. ⬜ **Watch memory closely once everything's running together** — 512MB
    total, shared between the jukebox app, and possibly mosquitto and
    shairport-sync if they're colocated too. The jukebox app alone is tiny
    (~47MB RSS observed on the Pi 3), but the combined footprint on the
    Zero hasn't been measured yet since nothing's running there but the
    venv/kernel module so far.

## Explicitly out of scope for this port

Running Claude Code itself on the Zero — Node.js dropped official `armv6l`
binaries years ago (only unofficial community builds exist), and even if
that worked, a single ARM11 core + 512MB is a poor fit for it alongside the
actual jukebox workload. Manage the Zero remotely over SSH from wherever
Claude Code already runs instead — the same pattern already used for the
Mac (`MusicAppSSHWorker`) and this Pi 3.
