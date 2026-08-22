# jukebox_panel Linux kernel module

A pair of Linux kernel drivers that bit-bang GPIO to talk directly to the
jukebox's original panel electronics — two shift-register digit displays,
two indicator LEDs, and a 12-key scanned matrix keypad — replacing the
Arduino firmware (`docs/ArduinoRefJukeboxPanel/`) that originally drove
this hardware. Living in the kernel keeps the bit-bang timing tight and
free of userspace scheduling jitter; everything above this (`src/panel/`)
just opens a character device and reads/writes bytes.

For the physical wiring this expects, see [`WIRING.md`](WIRING.md). For
the full functional behavior built on top of this driver (keypad state
machine, animations, MQTT integration), see
[`docs/SPECIFICATION.md`](../../docs/SPECIFICATION.md).

## Two drivers, same hardware, pick one

This directory builds two independent, mutually-exclusive kernel modules.
They drive the exact same GPIO lines, so **only one is ever loaded at
once** — loading both would have them fight over the same pins.

| Module | Device | Protocol |
|---|---|---|
| `jukebox_panel.c` | `/dev/jukebox_panel` | Line-based ASCII, mirrors what the original Arduino firmware spoke over serial |
| `jukebox_panel_bin.c` | `/dev/jukebox_panel_bin` | Fixed 8-byte binary commands, lower latency, exposes raw segment control |

[`jukebox-panel.modules-load.conf`](jukebox-panel.modules-load.conf) is
what actually gets autoloaded at boot on this project's device: currently
`jukebox_panel_bin`.

## The hardware being driven

- **Two digit displays** (3-digit and 4-digit), each driven by an
  MM5450/MM5451 LED driver chip over a shared serial shift-register bus.
- **Two indicator LEDs**, wired into unused high bits of the 4-digit
  display's own shift-register word rather than having dedicated lines.
- **A 12-key matrix keypad** (`0`–`9`, `P`, `R`), scanned rather than wired
  as discrete buttons — it reuses the display bus's data/select lines as a
  3-bit scan address while a shared enable line is held low, then reads
  two dedicated row-input lines back.

Both drivers use the same 7 GPIO lines (BCM numbering), overridable as
module parameters (e.g. `options jukebox_panel gpio_clock=17 ...` via
`/etc/modprobe.d/`) rather than requiring a rebuild:

| Signal | Param | Default BCM GPIO | Direction |
|---|---|---|---|
| Shift clock | `gpio_clock` | 17 | Pi → board |
| Display/keypad-scan enable | `gpio_enable` | 27 | Pi → board |
| 4-digit display data | `gpio_data4` | 22 | Pi → board |
| 3-digit display data | `gpio_data3` | 23 | Pi → board |
| Matrix select (scan address bit 2) | `gpio_matrix_c` | 24 | Pi → board |
| Keypad row input 0 | `gpio_keypad_in0` | 25 | board → Pi |
| Keypad row input 1 | `gpio_keypad_in1` | 5 | board → Pi |

## Display protocol: shift-register bit-banging

Both drivers hold a `display3_line`/`display4_line` 32-bit word each and
push a full 36-clock frame to update the hardware — the MM5450/MM5451 has
no separate load/latch signal; it auto-latches after the 36th clock:

1. Raise `enable`.
2. Clock out a **start bit** (both data lines driven high).
3. Clock out **32 data bits, LSB first** — the packed display word.
4. Clock out **3 zero filler bits** (the chip has 35 usable outputs; only
   32 are used here).
5. Drop `enable`.

Each clock phase (`write_bit()`) holds for `bit_delay_us` (default 400µs)
on both the low and high half — generous, inherited from the original
16MHz Arduino's timing rather than tuned to this hardware; see
[`docs/displayCorruptionInvestigation.md`](../../docs/displayCorruptionInvestigation.md)
for why this dwell time actually matters on the Pi's current wiring.

`gpio_mutex` serializes every GPIO access in both drivers — display writes
and keypad scans share the same physical lines and must never interleave.

### Character encoding (text driver only)

`jukebox_panel.c` packs ASCII text into a display word itself: each
character maps to a 7-bit segment pattern (a lookup table for `0`–`9`/
`a`–`z`, space = blank, `-` = middle segment only, anything else falls
back to an underscore), and up to 4 characters are packed 7 bits each,
building the word by processing the string **last character to first** so
the first character ends up in the lowest 7 bits (and is therefore the
first thing shifted onto the wire). The binary driver instead only ever
renders decimal integers directly from an integer value (`JBP_CMD_SET_INT`)
or accepts a caller-supplied raw word (`JBP_CMD_SET_RAW`), doing no
character translation of its own.

The 4-digit display's word also carries the two LEDs in its otherwise-
unused top bits — right LED = bit 31, left LED = bits 29–30 (both set
together) — which every code path that touches that word takes care to
preserve rather than clobber.

## Keypad scan protocol

`scan_keypad_raw()` (identical logic in both drivers) drives an 8-step
scan: for each address `0`–`7`, it puts the address's 3 bits on
`data4`/`data3`/`matrix_c` (with `enable` held low so the display drivers
don't fight the scan), waits `keypad_settle_us` (default 50µs), then
samples both row-input lines into a 16-bit accumulator — row input 0
becomes bits 0–7, row input 1 becomes bits 8–15. "Nothing pressed" reads
as `0xFFFF`. A fixed table (`raw_to_key()`) maps each possible signature to
`0`–`9`/`R`/`P`.

**The two drivers debounce this signature differently:**

- **`jukebox_panel.c`** (text protocol): a leading-edge/lockout state
  machine. A non-idle signature is trusted and reported once it reads
  consistently for `keypad_confirm_ms` (default 10ms — long enough to
  reject electrical noise, short enough that switch bounce doesn't keep
  resetting it). After reporting, further changes are ignored for
  `keypad_debounce_ms` (default 50ms), and a new press isn't armed again
  until the scan reads idle for `keypad_confirm_ms` too — with a
  `keypad_rearm_timeout_ms` (default 300ms) safety net in case a noisy
  line never produces a clean idle read.
- **`jukebox_panel_bin.c`** (binary protocol): a rolling-window scheme. A
  signature is reported once it occurs at least `keypad_window_assert_count`
  times (default 6) within a trailing `keypad_window_ms` window, then
  stays "latched" — firing a repeat event every `keypad_repeat_interval_ms`
  (default 300ms) while held — until its occurrence count in that same
  window drops to `keypad_window_release_count` (default 2) or below.

## `/dev/jukebox_panel` — text protocol

| Write | Effect |
|---|---|
| `w3 <text>\n` | Write `<text>` (space-padded/truncated to 3 chars) to the 3-digit display |
| `w4 <text>\n` | Write `<text>` (space-padded/truncated to 4 chars) to the 4-digit display |
| `led0\n` / `led0 1\n` | Right LED off / on |
| `led1\n` / `led1 1\n` | Left LED off / on |
| `off\n` | Blank both displays AND both LEDs |
| `c\n` | Blank both displays, LEDs untouched |

`read()` blocks until a button settles, then returns `BTN:<c>\n` where
`<c>` is `0`–`9`, `R`, or `P` — already decoded from the raw signature.
Multiple concurrent readers are supported (a FIFO delivers each event to
exactly one waiting reader); opening the device clears any events already
queued, so every fresh `open()` starts from a known-clean state.

## `/dev/jukebox_panel_bin` — binary protocol

Every `write()` must supply exactly 8 bytes — one
`struct jbp_bin_cmd { u8 cmd; u8 target; u8 _pad[2]; u32 value; }`
(see [`jukebox_panel_bin_protocol.h`](jukebox_panel_bin_protocol.h)); any
other size is rejected with `-EINVAL`, and there's no partial-write
reassembly across calls.

| `cmd` | Name | Effect |
|---|---|---|
| 1 | `JBP_CMD_SET_INT` | Display an unsigned decimal integer, right-justified, on `target` (`JBP_TARGET_3DIGIT`=0 / `JBP_TARGET_4DIGIT`=1). Rejected outright (not truncated) if it doesn't fit. Preserves current LED state. |
| 2 | `JBP_CMD_SET_RAW` | Set `target`'s raw 32-bit shift-register word directly, bypassing character translation. For the 4-digit display this includes the LED bits; the driver's LED-state tracking updates to match. |
| 3 | `JBP_CMD_SET_LED` | Set right (`JBP_LED_RIGHT`=0) or left (`JBP_LED_LEFT`=1) LED on/off per `value`, leaving segments untouched. |

`read()` returns a stream of **raw, undecoded** 2-byte keypad signatures
(native-endian `u16`), one per settled key-state change — unlike the text
protocol, this driver leaves signature→character translation entirely to
the caller.

## Building and installing

```sh
make                 # builds both jukebox_panel.ko and jukebox_panel_bin.ko
sudo make install    # installs to /lib/modules/$(uname -r)/extra, runs depmod
```

[`99-jukebox-panel.rules`](99-jukebox-panel.rules) (a udev rule) makes
either device node group-owned by `gpio`, mode `0660`, once loaded.
[`jukebox-panel.modules-load.conf`](jukebox-panel.modules-load.conf)
autoloads the chosen module (`jukebox_panel_bin`) at boot via
`systemd-modules-load`.

To load/unload manually instead (e.g. while testing the other protocol):

```sh
sudo make load        # insmod jukebox_panel.ko   -> /dev/jukebox_panel
sudo make unload       # rmmod jukebox_panel

sudo make load-bin     # insmod jukebox_panel_bin.ko -> /dev/jukebox_panel_bin
sudo make unload-bin    # rmmod jukebox_panel_bin
```

Never load both at once — see WIRING.md's GPIO table.

## Testing without any Python involved

With `jukebox_panel` loaded, see [`WIRING.md`](WIRING.md#validating-the-wiring)
for `echo`/`cat` commands against `/dev/jukebox_panel` that exercise every
text-protocol command and print `BTN:<c>` lines as keys are pressed.
