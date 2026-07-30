# Porting to an original Raspberry Pi Zero

Status: **hardware/dependency layer verified working; alpha displays and
panel keypad both wired up and verified working (all 12 keys confirmed).**
Device is up as `jukebox0`,
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

- `linux/jukeboxPanelModule/` (the keypad kernel driver) uses the generic
  BCM-numbered `gpio_request()` API, not hardcoded memory addresses — same
  interface across the whole 40-pin Pi lineup. Built clean with `make`
  against the already-installed matching kernel headers (no extra headers
  package needed — see step 4), installed with `sudo make install`,
  loaded with `modprobe jukebox_panel_bin`, registered
  `/dev/jukebox_panel_bin` correctly (confirmed in `dmesg`), and opened
  successfully as `simonbs` once the udev rule/group were in place.
  **Now wired and verified against real button presses**, using
  `src/utils/test_keypad.py` (a standalone driver-only test script, no
  displays/MQTT/coordinator involved): all 12 keys (`0`–`9`, `P`, `R`)
  decode correctly, including two genuinely separate presses of the same
  key registering as two distinct, correctly-timed events.

  **Background noise, root-caused**: a persistent signature (`0xfdff`,
  one bit off from idle on `keypad_in1`/GPIO5) fires continuously
  regardless of what's wired. Ruled out by direct elimination: the
  TXS0108E level shifter (swapped for a 10k/18k resistor divider — no
  change), the mechanical switches (persisted with buttons physically
  removed entirely), undervoltage (`vcgencmd get_throttled` → `0x0`), and
  breadboard crosstalk (a pull-up added in `jukebox_panel_bin.c`'s
  `configure_keypad_input_bias()` made no difference *while* the divider
  was attached). Root cause confirmed by elimination-of-elimination: with
  the keypad lines disconnected from the GPIO pins entirely, the noise
  vanished completely — meaning the divider's own 18kΩ-to-GND leg was
  the whole time overpowering the Pi's weak internal pull-up (~50–65kΩ)
  whenever nothing external actively drove the line high. Not a
  crosstalk/routing issue; a resistor-divider-vs-pull-up mismatch. Worth
  keeping in mind for the PCB: a plain resistive divider needs a defined
  idle-high source of its own (or use an active level shifter like the
  TXS0108E instead), since a weak Pi-side pull-up can't be relied on to
  win against it.

  **Fixed the real impact, not just the symptom**: the original
  leading-edge/lockout debounce design used one shared "current value"
  slot, so the persistent noise could occupy it and block detection of
  real keypresses on a different signature — measured directly as ~640ms
  first-press latency and a quick 12-key tap round catching only 8.
  Rewrote `keypad_scan_thread_fn()` as a rolling-window majority debounce:
  each raw signature is tracked independently (up to `KEYPAD_MAX_LATCHED`
  at once) against its own occurrence count in a trailing
  `keypad_window_ms` window, asserting at `keypad_window_assert_count`
  occurrences and releasing at `keypad_window_release_count` — so a
  chronically-noisy signature latches and repeats on its own without
  starving detection of anything else. All four new parameters
  (`keypad_window_ms`, `keypad_window_assert_count`,
  `keypad_window_release_count`, `keypad_repeat_interval_ms`) are
  live-tunable via sysfs, same as the driver's existing params.
  `keypad_window_release_count` was bumped live from the default 2 to 4
  during testing. Built and loaded on `jukebox0`; verified end-to-end
  with a full 12-key round, each key pressed twice with genuine
  separation — all 24 presses registered correctly. **Currently
  uncommitted** in `linux/jukeboxPanelModule/jukebox_panel_bin.c` on both this
  checkout and `jukebox0`'s (the earlier pull-up change is folded into
  this same uncommitted diff). `linux/jukeboxPanelModule/jukebox_panel.c` (the
  dormant ASCII-protocol sibling driver, not currently loaded) has the
  same underlying design issue and was deliberately left untouched since
  it's unused.

  Keypad is now on the custom PCB (contacts were being cleaned as of the
  last test round) rather than the breadboard prototype described above
  for the level-shifter/divider experiments.
- I2C/display code (`src/drivers/led16_display.py`) goes through Blinka's
  board-detection layer, not a hardcoded I2C bus number. Confirmed in
  `adafruit_platformdetect/revcodes.py`: "Zero" (`0x09`), "Zero W" (`0x0C`),
  and "Zero 2 W" (`0x12`) are all explicitly recognized revision codes.
  **Now verified against real hardware, not just code inspection**:
  `i2cdetect -y 1` found devices at `0x70`–`0x74`, exactly matching the two
  `led16_display` instances `main.py` constructs (`addr=(0x70, 0x71)` for
  the 8-char display, `addr=(0x72, 0x73, 0x74)` for the 12-char display).
  Ran the actual driver against them (`led16_display(addr=...).write(...)`)
  and both displays lit up with the expected text, visually confirmed by
  the user. One unexplained device also showed up at `0x4d` — not used by
  either display, source unidentified, worth investigating before final
  wiring.
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
3. ✅ **Enable I2C**: `sudo raspi-config nonint do_i2c 0` — done. **Correction:**
   this step was originally marked done but hadn't actually taken effect —
   `/boot/firmware/config.txt` still had `dtparam=i2c_arm=on` commented out
   and `/dev/i2c-1` didn't exist. Re-ran `do_i2c 0` (confirmed via
   `raspi-config nonint get_i2c` flipping `1`→`0` and the config.txt line
   getting uncommented) and rebooted; `/dev/i2c-1`/`/dev/i2c-2` exist now
   and `i2cdetect` sees the displays (see below).
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
   `cd linux/jukeboxPanelModule && make && sudo make install`, then
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
7. ✅ **Wire the hardware** — done, on the current breadboard prototype.
   Alpha displays (I2C) and panel keypad (all 12 keys) are both physically
   connected and verified working for held/well-paced presses (see above
   for the caveat on quick sequential taps, not yet resolved on this
   assembly). Same physical GPIO/I2C wiring as the Pi 3 box applies; BCM
   pin numbering is consistent across the Pi lineup, see
   `linux/jukeboxPanelModule/WIRING.md`. **A custom PCB is planned to replace
   this breadboard assembly** — re-verify keypad reliability once it's in.
8. ⬜ **Adapt `src/config.ini`** for the new host — not done yet: `[mqtt]`
   broker address (wherever it actually runs — locally on the Zero, or
   remote), `[sshWorker]` settings unchanged in shape but double-check paths.
9. 🟡 **Decide where mosquitto/shairport-sync run** — partially done.
   `mosquitto` (the broker, not just the `libmosquitto1` client lib the
   app's own dependencies pull in) is now installed on `jukebox0` via
   `sudo apt install mosquitto`, running (`active`/`enabled`), and
   verified end-to-end with `mosquitto_pub`/`mosquitto_sub` over loopback.
   Still open: whether it actually stays local long-term vs. left on the
   existing box, and `shairport-sync` placement hasn't been decided or
   installed at all yet.
10. ✅ **Adapt the systemd unit** (`systemd/jukebox.service`) — done. Since
    `jukebox0`'s checkout already lives at `/home/simonbs/jukebox5` under
    `simonbs`, matching the Pi 3 layout, the unit needed no edits — just
    installed as-is: copied to `/etc/systemd/system/jukebox.service`,
    `systemctl daemon-reload`, `enable`, `start`. Confirmed running
    (`systemctl status` active, journal shows SSH-to-Mac connecting and 198
    playlist tracks loading) and enabled for boot
    (`multi-user.target.wants/jukebox.service` symlink created).
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
