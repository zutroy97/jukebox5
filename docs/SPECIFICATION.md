# Jukebox5 — Functional Specification

**Purpose of this document.** This describes what the jukebox application
*does* and *why*, in enough detail that someone with no access to this
repository's source code could build a different implementation — in any
language, with any architecture — that behaves identically from the
outside: same protocols on the wire, same things appear on the displays at
the same times, same buttons do the same things. It intentionally avoids
describing *how the existing Python/C code is organized internally*
(module names, class names, function names) except where a mechanism is
genuinely part of the observable behavior (e.g. a wire protocol). Where
implementation-specific terms are unavoidable for precision, they're
called out as such.

---

## 1. What this system is

A Raspberry Pi–based jukebox controller. It:

- Receives AirPlay audio metadata (artist/title/album, play/pause/stop
  events) from `shairport-sync` via MQTT, and displays it on two
  14-character alphanumeric LED displays.
- Drives a custom physical control panel with two multi-digit 7-segment
  displays, two indicator LEDs, and a 12-key matrix keypad, salvaged/
  adapted from an actual jukebox.
- Lets the user type a 3-digit code on the keypad to queue a specific
  track (looked up in a local playlist file), or type short
  letter+digit "commands" to control playback (play/pause, next, previous).
- Reflects system state — a song currently playing, a keypad selection in
  progress, playback paused, the MQTT connection to shairport-sync lost,
  or nothing playing at all — on the panel and the two alphanumeric
  displays in real time.

## 2. Hardware inventory

| Component | Description |
|---|---|
| **3-digit 7-segment display** | Driven by an MM5450/MM5451 LED driver chip. Shows a rolling "songs played" counter. |
| **4-digit 7-segment display** | Driven by a second MM5450/MM5451 chip. Shows the currently-playing track's playlist index (offset +100), the digits the user is currently typing on the keypad, post-entry blink/error feedback, or a paused-flash of the track number. Its top bits also carry the two indicator LEDs (see below) — it is wired into the same shift-register chain as the LEDs. |
| **Right LED ("Selection Playing")** | Lit exactly when the track currently playing was found in the local playlist (i.e. the 4-digit display is showing a real playlist index rather than a placeholder). |
| **Left LED ("Selections being made")** | Lit exactly while the user has an in-progress, not-yet-complete keypad entry (digits or a `P`-command). |
| **12-key matrix keypad** | Keys `0`–`9`, `P`, `R`. Wired as a scanned matrix, not discrete buttons — see §3.2. |
| **Two 14-segment alphanumeric displays** | HT16K33-based, I2C, "Seg14x4" style, 4 characters each, used together as a virtual 8-character "label" line + 12-character "value" line (I2C addressing lets each logical display span multiple physical HT16K33 chips — the 8-char label display is 2 chips at `0x70`/`0x71`, the 12-char value display is 3 chips at `0x72`/`0x73`/`0x74`). Shows the currently playing song's Artist/Title/Album (label/value pairs), or status messages. |

The panel board (3-digit display, 4-digit display, 2 LEDs, keypad) was
originally built for a 5V/16MHz Arduino. In the Raspberry Pi build, GPIO
runs at 3.3V and is not 5V-tolerant, so a TXS0108E (or equivalent
auto-direction-sensing level shifter) sits between the Pi and the panel
board. Every signal is unidirectional (the Pi always drives clock/enable/
data3/data4/matrix-select; the board always drives the two keypad row
lines back), so no direction-control pins are needed on the shifter.

## 3. Low-level wire protocols

These are the actual physical/electrical contracts. A clean-room
reimplementation only needs to reproduce these exactly if it's also
talking to the *same physical panel board*; if reimplementing against a
software-simulated panel, only the semantics in §5 onward matter.

### 3.1 Digit-display protocol (MM5450/MM5451 shift register)

Each of the two digit displays is driven by an MM5450 or MM5451 chip,
which accepts a synchronous serial stream on a shared clock line, with
**no separate load/latch signal** — the chip auto-latches after the 36th
clock pulse of a frame. There are two independent data lines (one per
display) sharing one clock, so both displays' chips are updated together
in lockstep every frame, even if only one display's content changed.

A full update is exactly **one start bit + 35 data bits = 36 clock
pulses**:

1. Raise the shared **enable** line.
2. **Start condition**: drive *both* data lines HIGH, pulse the clock low
   → high, hold. This is bit 1 of the frame (a logical "1").
3. **Data phase**: shift out 35 more bits, one clock pulse each, **LSB
   first**:
   - The first 32 bits come from each display's packed 32-bit segment
     word (see §3.3 for the bit layout).
   - The remaining 3 bits are always zero (filler — the chip has outputs
     1–35 but only outputs 1–32 are used here).
   - For each bit: place the bit's value on each data line, pulse the
     clock low then high, with an equal dwell after each clock edge
     (400µs by default in this implementation, tunable — chip timing
     requirements are loose; this Pi-based implementation just reused
     conservative timing from the original 16MHz Arduino version).
4. Drop the enable line. (The chip already latched the pattern
   internally at clock 36; dropping enable just returns the driving
   side to its idle level between writes.)

Bit 1 after the start bit lands on the chip's Output 1, bit 2 on Output
2, etc. — so the low-order bit of the packed word is the first character
position, in the sense described next.

### 3.2 Keypad matrix scan protocol

The keypad is not discrete buttons — it's read as a scanned matrix, and
it **reuses the two display data lines plus one more line (called
"matrix select") as a 3-bit address bus** while the shared enable line is
held low (disconnecting the display drivers so they don't fight the
scan). Two more, keypad-only lines are read back as the scan result.

For each of **8 scan steps** (address 0–7):

1. Drive the 3-bit address on the shared lines: LSB on the 4-digit data
   line, next bit on the 3-digit data line, MSB on the matrix-select
   line.
2. Wait a short settle time (50µs in this implementation, runtime-tunable
   via the `keypad_settle_us` module parameter -- raised from an original
   5µs while chasing a spurious-signature issue, though later testing
   against real hardware found no measurable difference between 5µs and
   50µs; kept at the more generous value anyway since there's no real
   cost to it).
3. Sample both keypad row-input lines. Row-input-1's reading becomes bit
   `i` of a 16-bit accumulator; row-input-0's reading becomes bit `i+8`.

After all 8 steps, the 16-bit accumulator is a **signature** unique to
whichever keypad contact (if any) is currently shorted by a pressed key.
"Nothing pressed" reads as `0xFFFF` (every bit set — both row lines
idle-high at every step). The signature-to-character mapping is a fixed
lookup table (see §3.4 for the actual values, since two different
character labelings of the *same* physical signatures exist — see the
remapping note below).

After scanning, the shared address lines must be driven back to their
*display-idle* level (all low) before returning to display duty, or the
keypad scan's address bits bleed onto the display shift-register lines.

**Debounce**: the raw signature is sampled continuously (e.g. once every
5ms), using a leading-edge/lockout design rather than "wait for
continuous stability, then report": a non-idle signature is trusted (and
reported) as soon as it's read consistently for a short confirm window
(`keypad_confirm_ms`, 10ms default) — long enough to reject single-sample
electrical noise, short enough that a worn switch's own bounce doesn't
keep resetting it before it ever accumulates enough continuous stable
time (the failure mode of an earlier "must stay perfectly still for the
whole debounce window" design this replaced, which could silently drop a
genuine tap entirely under exactly that kind of bounce). After reporting,
all further signature changes are ignored for a lockout period
(`keypad_debounce_ms`, 50ms default) — covering the rest of that same
bounce — and a new press isn't recognized until the scan reads idle for
`keypad_confirm_ms` too, confirming the key was actually released. If
that clean idle read never comes (observed on real hardware: a
sufficiently noisy line can bounce indefinitely and never sit still), a
bounded safety-net timeout (`keypad_rearm_timeout_ms`, 300ms default)
forces re-arming anyway, trading the "reported exactly once per press"
guarantee for an unusually long hold in exchange for the keypad never
getting stuck unresponsive.

### 3.3 Character encoding

**7-segment digits/letters** (for the two digit displays): each character
position is a 7-bit segment mask (segments a–g). A lookup table maps
`'0'`–`'9'` and `'a'`–`'z'` (case-insensitive) to their 7-bit patterns; a
space is `0`; `'-'` is `8` (just the middle segment); anything else falls
back to `32` (just segment g, reading as an underscore). Up to 4 character
positions are packed into one display's 32-bit word, 7 bits each,
**most-significant character first after reversing the source string** —
i.e. build the word by processing the string's characters from *last* to
*first*, shifting the accumulator left 7 bits and OR-ing in each
character's pattern each time. This lands the *first* character of the
string in the lowest 7 bits of the final word (and therefore is the
*first* thing shifted out onto the wire, landing on Output 1). A 3-digit
display only meaningfully uses 3 of the 4 possible character slots; a
4-digit display uses all 4 — and the 4-digit display additionally
overlays its two indicator LEDs into the packed word's otherwise-unused
top bits: bit 31 = right LED, bits 29–30 (both set together) = left LED.
Any write to the 4-digit display's raw word must preserve (OR in) the
current LED bits, or it silently turns the LEDs off as a side effect.

Right-justified integer display (e.g. "show the number 42 on the 3-digit
display") blank-pads on the left rather than truncating, and rejects
values that don't fit the digit count rather than silently truncating
them.

**14-segment alphanumeric** (for the two label/value displays): standard
ASCII-range character-to-16-bit-segment-pattern mapping (the extra 2 bits
beyond 14 segments cover the decimal point and, on this hardware, a
colon/comma convention). A `.` or `,` character does not consume its own
character position — it's folded into the *previous* character's pattern
as an extra lit segment (matching how 14-segment alphanumeric displays
conventionally handle a trailing decimal point without wasting a whole
digit position on it).

### 3.4 Text-protocol kernel driver (reference: `/dev/jukebox_panel`)

A line-based ASCII protocol over a character device, mirroring what the
original Arduino firmware spoke over a serial port:

| Write | Effect |
|---|---|
| `w3 <text>\n` | Write `<text>` (space-padded/truncated to 3 chars) to the 3-digit display |
| `w4 <text>\n` | Write `<text>` (space-padded/truncated to 4 chars) to the 4-digit display |
| `led0\n` / `led0 1\n` | Right LED off / on |
| `led1\n` / `led1 1\n` | Left LED off / on |
| `off\n` | Blank both displays AND both LEDs |
| `c\n` | Blank both displays, LEDs untouched |

| Read | Effect |
|---|---|
| blocks until a keypad button settles, then returns `BTN:<c>\n` | `<c>` is one of `0`–`9`, `R`, `P` |

Multiple concurrent readers are supported (each settled button event is
delivered to exactly one waiting reader, not broadcast to all — readers
compete for events from a shared FIFO). Opening the device clears any
events already sitting in that FIFO first, so a fresh open() always
starts from a known-clean state rather than potentially receiving a
leftover event queued before this reader existed (e.g. one settled right
as a previous reader exited without consuming it). With more than one
reader open at once, a later open() clears events an earlier one hasn't
consumed yet too — an accepted tradeoff for this device's actual usage
(normally exactly one long-lived reader).

Character-remapping note: this text protocol's signature→character table
is the **original, unmodified** mapping straight off the physical
keypad's wiring. A *separate* remapping (0↔5, 1↔6, 2↔7, 3↔8, 4↔9; `R`/`P`
unchanged) exists only in the higher-level binary-protocol path described
next — it's a deliberate relabeling decision made at the application
layer, not a hardware fact, and is **not** applied to the text protocol.
A clean-room implementation should treat the raw hardware mapping (§3.2's
table) as ground truth and decide independently whether to apply this
same 0↔5/1↔6/2↔7/3↔8/4↔9 relabeling at whatever layer it chooses.

### 3.5 Binary-protocol kernel driver (reference: `/dev/jukebox_panel_bin`)

A fixed-size binary alternative to §3.4, exposed as a separate device
(only one of the two protocol drivers is ever active at a time — they'd
otherwise contend for the same hardware lines). Chosen for lower latency
and to allow raw segment-level control (needed for the segment-reveal
animation described in §6.4).

Every `write()` must supply **exactly 8 bytes**, one fixed-layout command:

```
struct { uint8_t cmd; uint8_t target; uint8_t _pad[2]; uint32_t value; }
```

| `cmd` | Name | Effect |
|---|---|---|
| 1 | `SET_INT` | Display an unsigned decimal integer, right-justified, on the display named by `target` (0 = 3-digit, 1 = 4-digit). Value must fit (0–999 / 0–9999) or the write is rejected outright rather than silently truncated. Preserves current LED state. |
| 2 | `SET_RAW` | Set the named display's raw 32-bit shift-register word directly (see §3.3's bit layout), bypassing character translation entirely. For the 4-digit display this includes the LED bits; the driver's internal LED-state tracking updates to match whatever bits were just set, so a later `SET_LED` behaves consistently. |
| 3 | `SET_LED` | Set right LED (`target=0`) or left LED (`target=1`) on/off per `value` (0/nonzero), leaving segments untouched. |

Every `read()` returns a stream of raw, **undecoded** 2-byte keypad
signatures (native-endian `uint16_t`), one per settled/debounced key
change — translating a signature to a character is left entirely to the
caller (unlike the text protocol, which decodes on the driver side).
Multiple readers, FIFO delivery, and the same debounce algorithm as §3.2
all apply identically.

---

## 4. Software architecture, top-down

Four layers, each replaceable independently:

1. **Panel driver** — talks to the actual panel hardware (or a serial
   Arduino intermediary, or nothing/a simulator) and exposes a small,
   hardware-agnostic interface (§5).
2. **Display/state orchestration** — a single coordinating loop that owns
   all writes to the panel and the two alphanumeric displays, so hardware
   access (I2C, a character device, a serial port) is never touched from
   more than one thread at a time. Everything that wants to change what's
   on screen posts a request to this loop rather than writing to hardware
   directly (§6).
3. **Animated text rendering** — a small state machine per text line that
   handles typing text onto a display character-by-character (or
   segment-by-segment), wrapping long text across multiple "pages", and
   clearing (§6.3–6.4).
4. **Application logic** — MQTT integration with shairport-sync (§9),
   keypad-driven track selection and remote commands (§7), the playlist
   (§10), and wiring all of the above together per a config file (§11).

A guiding invariant throughout: **all hardware I/O for the panel and the
two alphanumeric displays happens on one single thread/loop.** Nothing
else is allowed to write to those devices directly. This matters because
the underlying transports (I2C, a shared character device, a serial
port) are not safe for concurrent access from multiple threads, and
serializing everything through one loop sidesteps that entirely rather
than requiring a lock around every hardware call.

---

## 5. Panel driver interface

Whatever panel driver is in use (talking to the real hardware via
either kernel protocol, or to an Arduino over serial, or a
software-only stand-in), it must expose this interface to the rest of
the system:

- `WriteToThreeDigitDisplay(text, animated=True)`
- `WriteToFourDigitDisplay(text, animated=True)`
- `ClearThreeDigitDisplay()` / `ClearFourDigitDisplay()`
- `RightLedSet(bool)` / `LeftLedSet(bool)`
- `Off()` — blank everything, LEDs included
- `Clear()` — blank both digit displays, **LEDs untouched**
- an inbound callback/event stream for settled keypad presses, each
  delivering one already-decoded character: `0`–`9`, `R`, or `P`
  (unrecognized/transient raw signatures are filtered out before
  reaching this layer — see §3.2's debounce algorithm)

**The `animated` parameter's contract** (only meaningful for a driver
capable of raw segment control): when `True` (the default), a driver
*may* play a segment-by-segment reveal animation for the write instead of
showing it instantly (see §6.4's panel-display reveal). Callers pass
`False` for writes where timing must stay exact or that repeat too fast
to animate sensibly:
- live echo of digits as the user types them on the keypad,
- the post-entry blink/error feedback sequence (§7),
- each phase of the paused-playback flash (§8.3).

A driver with no segment-level control (e.g. one that only speaks the
text protocol, or a serial-attached Arduino) is free to ignore
`animated` entirely and always write instantly — this is exactly what
this project's Arduino-serial and text-protocol drivers do; only the
binary-protocol driver actually implements the reveal.

---

## 6. Display/state orchestration

### 6.1 The single coordinating loop

One loop owns:
- a queue of pending work items (song updates, button presses, timeouts,
  message add/remove requests, pause/resume notifications, etc.) —
  anything that wants to change display state posts a closure/request
  onto this queue rather than acting directly;
- a list of registered "observers" (see §6.2);
- the keypad-entry state machine (§7);
- the paused-flash state machine (§8.3);
- the panel driver instance.

Each iteration:
1. Compute how long it's safe to sleep before *something* needs
   attention — the minimum of: any pending internal timeout, the keypad
   entry's next deadline (if entry is in progress or feedback is
   playing), the pause-flash's next toggle deadline (if paused), and
   every registered observer's own reported next-wakeup time (or "no
   deadline" if all are idle).
2. Block on the work queue for up to that long; if a work item arrives
   first, process it immediately.
3. Check the keypad-entry state machine's timeout (advance a blink/error
   feedback phase, or fully reset if idle).
4. Check the pause-flash state machine's timeout (toggle on/off).
5. Call `draw()` on every registered observer, letting each one advance
   its own animation state and write to its own display target.

An overall inactivity timeout (30 minutes, in this implementation) fires
a "no event received" notification to all observers if nothing at all
has happened in that long — mostly a safety net, not a normally-hit path.

### 6.2 Observer contract

Each "observer" owns one logical display surface (in this system: the
label line, the value line — together forming the artist/title/album
display — or the panel's digit displays, which are actually driven
directly by the coordinating loop rather than through this observer
interface). An observer is notified of:

- **Artist / Title / Album updated** (each independently — see §9's
  ordering guarantee)
- **Playback stopped** (display should return to idle/blank)
- **No event received in timeout period**
- **Custom message added/updated/removed** — a generic mechanism (used
  for "Weather: Sunny 72°F"-style ambient messages as well as the
  transient status messages described in §8.4/8.5) with:
  - `title` (also doubles as the message's unique key for later removal
    or update-in-place)
  - `text`
  - `ttl_s` — seconds until automatic removal; `0` means "persists until
    explicitly removed"
  - `display_s` — how long the message is held on screen once its turn
    in the rotation comes up (see §6.5)

  Expired messages are purged lazily, at the point any message-rotation
  bookkeeping runs.

Every observer also exposes `next_wakeup()` (seconds until it needs a
`draw()` call, or "none" if fully idle) and `draw()` (advance state,
write to hardware if needed) for the coordinating loop to drive.

### 6.3 Animated single-line text state machine

Each of the two alphanumeric-display "lines" (label, value) is driven
independently by the same kind of small state machine, parameterized by
its physical display width (8 for label, 12 for value in this system).
States, in the order text typically flows through them:

```
IDLE ──(new text set)──▶ TEXT_UPDATED ──▶ START_ANIMATION ──▶ ANIMATING
  ▲                                            ▲                  │
  │                                            │           (line fits width:
  │                                    ANIMATION_LINE_FINISHED_DELAY   go to
  │                                            ▲             ANIMATION_FINISHED;
  │                                    ANIMATION_LINE_FINISHED    doesn't fit:
  │                                            ▲             queue next page,
  └──────── ANIMATION_FINISHED_DELAY ◀── ANIMATION_FINISHED    go to
                  (only if looping)                            LINE_FINISHED)
```

Key behaviors:
- Setting new text always restarts from a clearing step (see §6.4) before
  the new text begins animating in — text never appears to overwrite old
  text in place character-by-character; it clears then reveals.
- If the text is longer than the display width, it's word-wrapped into
  multiple "pages" (breaking on whitespace, dropping the whitespace at
  the break) shown one after another, each held for a configurable delay
  before advancing to the next page.
- Once the *last* page finishes, if the display is configured to loop
  (used for the always-cycling label/value pair, not for one-shot status
  writes), it waits a configurable delay then restarts from the first
  page; if not configured to loop, it goes idle after a configurable
  hold delay instead of ever restarting on its own.
- Writing is diffed against what's already on screen character-by-
  character (space characters are never considered "changed", to avoid
  needless work clearing-then-rewriting blank regions) — each animation
  "tick" reveals the text so far up through one more character, and each
  newly-revealed character position is written via whatever
  character-reveal mechanism is active (§6.4).
- A configurable delay separates each character's reveal from the next.

### 6.4 Reveal and clear animations (pluggable)

Two independent, pluggable animation behaviors:

**Clearing a line before new text appears:**
- *Immediate* — the line blanks instantly.
- *Blank left-to-right* — each character position blanks one at a time,
  left to right, at a configurable per-character delay (used specifically
  for the "value" line/Title display in this system, purely as a visual
  flourish).

**Revealing each individual character once its turn comes up** (this is
distinct from clearing — it governs how *one* character, at its
position, transitions from blank to its final glyph):
- *Immediate* — the character's full pattern is written in one shot.
- *Segment-by-segment* — the character's target 16-bit segment pattern
  is decomposed into its individual set bits; one additional bit is
  lit per tick (in bit order) until the character is fully drawn, then
  the overall line-animation moves on to the next character position.
  This requires the underlying display to support raw per-segment
  writes (true of the 14-segment alphanumeric displays here). Both the
  per-character delay (how long a fully-drawn character is held before
  the *next* character starts) and the per-segment delay (how fast one
  character's own reveal proceeds) are independently configurable.

Both the 8-character label line and 12-character value line use
*segment-by-segment* character reveal by default in this system (each
independently configurable back to *immediate*), and the value line
additionally uses *blank left-to-right* clearing while the label line
uses *immediate* clearing.

**The panel's digit displays** get an analogous, independently-designed
reveal animation, available only through the binary-protocol driver
(§3.5) since it needs raw segment control: when a write's target segment
pattern differs from what's currently shown, each of up to 4 digit
positions that actually changed blanks immediately, then relights its
own target 7 segments one bit at a time (at a configurable per-segment
delay), all 4 digit positions animating **in parallel** rather than one
digit finishing before the next starts — so a digit that needs fewer
segments lit (e.g. "1") finishes revealing sooner than one that needs
more (e.g. "8"). Digit positions whose segments are *unchanged* from
what's currently displayed are left completely untouched — no
blank-then-reveal, no flicker. This reveal runs on its own timer/thread
so that queuing a new write to either digit display doesn't block
whatever else the application is doing while a previous reveal is still
in flight (the newest write always becomes the new target immediately;
an in-progress reveal retargets seamlessly rather than needing to finish
first). Passing `animated=False` to a digit-display write bypasses this
entirely — the exact target pattern is written and shown on the very
next hardware frame, and the reveal animator's tracked state is
resynced to match (so a *later* animated write correctly diffs against
what's actually on the hardware rather than stale state).

### 6.5 Label/value rotation (the artist/title/album + messages display)

The label line and value line together cycle through an ordered list of
(label, value) pairs, rebuilt whenever it's exhausted or a new song
starts:

1. The currently-known song fields, **in a configurable order** (default:
   Title, Artist, Album) — any field with no value (most commonly Album)
   is skipped entirely, not shown blank. If *neither* artist nor title is
   currently known, no song-field pairs are included at all (this is how
   the rotation degrades to "just custom messages, or fully idle" when
   nothing is playing).
2. Every currently-active custom message (§6.2), in the order they were
   added, each shown as (message title, message text).

Between each pair, the display holds on the just-finished pair for a
configurable pause before advancing to the next. If the rotation list is
completely empty (nothing playing, no active messages), both lines go
idle/blank rather than looping over nothing.

**New song arriving** interrupts whatever's currently showing and jumps
straight to showing the new song's first field pair immediately, rather
than waiting for the current pair's hold time to elapse. Coordinator-level
song delivery is guaranteed to arrive **artist, then album (if any), then
title, in that order** — the rotation is (re)built and the interrupt
happens only once title lands, since title is guaranteed to be the last
of the three to arrive for a given song, and by then the full set of
fields to show is known.

**A message being added or updated** (not removed) *also* interrupts
immediately and shows that message's (title, text) pair right away,
rather than being silently appended to the end of the rotation list to
wait its turn. This matters specifically for urgent, transient status
messages (§8.4, §8.5): if it only got appended to the end and waited its
natural turn, a short-lived status could be added and then removed again
before ever actually being shown, which is exactly what naive
"just append to rotation" behavior produces for a status message that
needs to be seen *immediately*, not eventually.

**Album updates arriving after the initial song display** (i.e. the
album tag shows up on the wire slightly later than artist/title) update
the *existing* Album entry in the current rotation list in place (or
remove it, if album becomes empty) rather than triggering a full
interrupt/rebuild — since title has already fired and the display is
already correctly mid-rotation, there's no need to jump back to the
front.

**When playback stops** (or the "no event received" timeout fires): the
known song fields are cleared, both lines are blanked, and the rotation
either goes idle (nothing else queued) or resumes cycling through
whatever custom messages are still active (skipping straight back into
the rotation rather than requiring a new song to kick it out of idle).

---

## 7. Keypad entry: track selection and remote commands

One state machine owns interpretation of raw keypad presses, and it owns
the 4-digit display and both LEDs for as long as an entry is in
progress.

**Mode is decided by the first keypress after idle:**
- A digit (`0`–`9`) starts **track-selection mode**: exactly 3 digits are
  accumulated (further non-digit presses are ignored mid-entry), each
  echoed onto the 4-digit display instantly (not animated) as it's
  typed, left-justified/blank-padded to 4 characters. A 10-second
  inactivity timeout between keystrokes cancels the entry if not
  completed.
- `P` starts **command-entry mode**: subsequent presses accumulate a
  short "P + digits" sequence, matched incrementally against a fixed
  table of known commands as each key arrives:
  - `PP` → play/pause toggle
  - `P111` → previous item
  - `P666` → next item
  - `P222` → **local-only**: skip the alpha display (§6.5) immediately to
    its next rotation item (song field or active status message),
    without touching playback or MQTT at all
  - `P911` → **local-only**: show the Pi's own LAN IP address in the
    alpha display's rotation for 30 seconds
  - the moment the accumulated sequence exactly matches a known command
    *and* isn't also a prefix of some other, longer command still in the
    table, it fires immediately (no need to wait for a timeout or a
    fixed length) and the entry ends. (No pair in the current table is
    prefix-ambiguous with another — e.g. `PP` and `P222` diverge at the
    second character — but if one were added, the shorter command would
    have to wait out the 2-second timeout below before firing, in case
    the longer one was still being typed.)
  - the moment the accumulated sequence can no longer possibly be a
    prefix of *any* known command, entry ends immediately as invalid —
    no need to wait out the timeout either.
  - A 2-second inactivity timeout between keystrokes (shorter than
    track-selection's, since commands are meant to be typed in one
    quick burst) cancels the entry if neither condition is hit first —
    unless the accumulated sequence exactly matches a known command (see
    above), in which case the timeout fires that command instead of
    cancelling.
  - `PP`, `P111`, `P666`, and `queue_next`/`nextitem` (the two remote
    commands track selection itself can trigger, above) are the only
    commands actually forwarded to shairport-sync over MQTT (§9); `P222`
    and `P911` are intercepted before that and handled entirely on this
    side.
- Pressing `R` at any time (even mid-entry) immediately cancels/resets
  whatever entry is in progress and returns to idle, discarding it.
- Any other digit/letter mid-entry that doesn't fit the current mode
  (e.g. a non-digit while in track-selection mode) is simply ignored,
  not treated as invalid input.

**On entering either mode**, the left LED ("Selections being made") turns
on and the right LED ("Selection Playing") turns off — the display can
only show one thing at a time (current-track display vs. entry-in-
progress), so these two LEDs are always mutually exclusive; entering
something always means the display briefly stops showing "what's
currently playing."

**Once track-selection mode completes** (3rd digit typed): the entered
3-digit code resolves to a playlist index by subtracting an offset —
which offset depends on the code's range:

| Code range | Playlist index | Behavior |
| --- | --- | --- |
| `300`–`500` | code − 300 | **Immediate play**: queued, then immediately skipped to via a `nextitem` remote command (§9) — interrupts whatever's currently playing. |
| `100`–`299`, `501`–`999` | code − 100 | Queued behind the current track (`queue_next`, §9) — starts once it ends, doesn't interrupt. |

If the resulting index matches a real playlist entry, this counts as
"valid"; otherwise it's "invalid" — either way, control passes to the
feedback sequence below. For the non-immediate range, the queued track
doesn't actually start playing right away; it takes effect only once
shairport-sync reports the new track over MQTT some time later, which is
why the display doesn't try to show the new selection as "now playing"
right away. The immediate-play range's `nextitem` follow-up shortcuts
that wait.

**Once command-entry mode resolves** (exact match or dead-end): if it was
an exact match, the corresponding remote-control command is dispatched
(§9) and this counts as "valid"; a dead-end sequence counts as
"invalid." Same feedback sequence either way.

**Post-entry feedback** (identical mechanism for both modes):
- **Valid**: the entered code (padded to 4 characters) blinks on the
  4-digit display — alternating shown/blank — a configurable number of
  times (default 3), at a configurable phase duration (default 250ms
  on, 250ms off). Not animated — exact timing matters, and a
  segment-reveal here would blur a crisp blink into a smear.
- **Invalid**: a fixed error string ("Err" by default) is shown, padded
  to 4 characters, for a configurable duration (default 2 seconds), also
  not animated. Track-selection invalid feedback has one override: if the
  playlist hasn't been fetched from the Mac yet at all (§10), the panel
  instead shows "----" for 5 seconds, and the alpha display shows a "no
  playlist from mac" status message for the same 5 seconds — distinct
  from an ordinary out-of-range code, which still gets the standard "Err".
  Command-entry's invalid feedback is never affected by this, regardless
  of playlist state.
- Input is ignored entirely while this feedback sequence is playing out.
- Once feedback finishes (or an entry is cancelled via `R`, or times out
  with nothing typed at all), the left LED turns off, and the 4-digit
  display and right LED both revert to whatever they were showing
  *before* entry started — i.e. the currently-known playing track's
  index and its "is a known playlist track" status, cached across the
  whole entry so a track actually changing mid-entry doesn't clobber the
  digits the user is actively typing.

---

## 8. Playback/display state features

### 8.1 Normal operation — song playing

Artist/Title/Album cycle per §6.5. The panel's 4-digit display shows the
current track's playlist index + a fixed offset (100 in this
implementation — so playlist index 1 displays as "101"), or a placeholder
(`----`) if the currently playing track isn't found in the local
playlist by its persistent ID. The right LED tracks whether a real index
is being shown. The 3-digit display shows a simple incrementing counter
of songs played since the app started (not persisted across restarts).

### 8.2 Paused

While shairport-sync reports playback paused (see §9 for exactly which
MQTT signal this is), the 4-digit display **flashes** — alternating
between showing the current track index and blanking — at a configurable
interval (default 750ms per phase; i.e. ~1.33Hz full on/off cycle).
Both phases write unanimated (exact timing, same reasoning as §7's
blink feedback — a segment reveal would eat into the flash window and
blur each toggle into a slow re-materialize instead of a crisp blink).

An in-progress keypad entry (§7) always takes priority — the flash never
overwrites digits the user is actively typing; it simply resumes once
entry finishes.

Un-pausing (or playback stopping entirely — see §8.4) immediately stops
the flash and returns the 4-digit display to steadily showing the
current track index.

### 8.3 (reserved — folded into 8.2)

### 8.4 Connection to shairport-sync lost

If the MQTT connection to the broker drops, a message with title
"Problem" and text "MQTT Lost. Attempting Reconnect." is added to the
label/value rotation (§6.5) with no expiry (persists until explicitly
removed) — per §6.5's interrupt behavior, this is shown immediately
rather than waiting its turn. Once the connection is re-established, the
message is explicitly removed.

### 8.5 Idle / nothing playing (post-timeout)

Separately from a single track ending, shairport-sync tracks a broader
"active" state that only ends after a configurable idle grace period
(`active_state_timeout` in shairport-sync's own config, 10 seconds by
shairport-sync's own default; not overridden in this deployment) with no
playback resuming. When that broader idle state ends: both panel
digit displays are cleared (blanked), the right LED turns off, and a
message with title "Playback" and text "stopped" replaces whatever was
showing on the label/value display — again shown immediately per §6.5's
interrupt rule, and again respecting an in-progress keypad entry (the
panel clear is skipped if the user is mid-entry, though the cached
"idle" track state is still updated so it takes effect once entry ends).
This status is automatically cleared as soon as a real song update
arrives again — it must not linger and reappear later in the rotation
once real playback resumes.

---

## 9. MQTT integration with shairport-sync

Connects to an MQTT broker (host/port/topic-prefix all configurable) and
subscribes to shairport-sync's own built-in MQTT metadata publisher
(distinct from any *separate* MQTT bridge project — this is the
`mqtt { enabled = "yes"; ... }` block of shairport-sync's own config).
Subscribed topics, under a configurable base topic (default
`shairport-sync`):

| Topic suffix | Meaning | Action |
|---|---|---|
| `/artist` | Artist tag arrived | Update known artist |
| `/title` | Title tag arrived | Update known title |
| `/album` | Album tag arrived | Update known album (never triggers a display update on its own — see below) |
| `/track_id` | A new track's opaque ID arrived | If different from the last known ID, flush all previously-known metadata for the outgoing track (artist/title/album, and the "already fired for this track" flag) before adopting the new ID |
| `/play_end` | The current track's audio stream ended | Flush all known metadata; notify the display layer to clear/return to idle |
| `/play_flush` | Playback paused (AirPlay "flush") | Notify the display layer (§8.2) |
| `/play_resume` | Playback resumed after a pause | Notify the display layer (§8.2) |
| `/active_end` | The broader "active" session ended (idle past the configured grace period with no new play starting) | Notify the display layer (§8.5) |

**Song-changed firing rule**: artist and title are the two required
fields; album is optional and, if it hasn't arrived yet by the time
artist+title are both known, the song is announced anyway without
waiting for it (album is folded in later, in place, if/when it shows up
— see §6.5). A "song changed" notification fires **at most once per
track** — guarded by a flag that's only cleared when a new `track_id`
arrives (or, as a fallback, when a fresh `/artist` message arrives after
already having fired once for the current track, in case the broker
never publishes `track_id` at all or it arrives out of the expected
order).

**Remote control**: `playpause`, `nextitem`, `previtem`, and "immediate
play" track selections (§7) can be sent either as *direct Music.app
control* over the `[sshWorker]` SSH connection described in §10
(JavaScript for Automation — `playpause.js`/`next_track.js`/
`previous_track.js`/`play_track.js`, run via `MusicAppSSHWorker`), or
through shairport-sync's own MQTT `/remote` topic (plain command
strings, or an explicit `queue_next <persistent_id>`) — configurable via
`remote_control_mode` (§11): `"jxa"`, `"mqtt"`, or `"fallback"`.

Direct JXA control exists as an alternative because shairport-sync's
MQTT remote control has no acknowledgment of whether a command actually
reached or took effect on the AirPlay source, and was observed failing
silently even with a live AirPlay session during real-world use — JXA
gives a real exit status instead. `"fallback"` mode starts on MQTT and
permanently switches to JXA once a configurable number of MQTT commands
have gone unacknowledged within a configurable trailing window (a
one-way switch for the rest of the process's run, not a retry loop —
re-testing a path already proven unreliable just risks repeating the
same silent failures). Regardless of mode, `"jxa"`/`"fallback"` both
behave as plain `"mqtt"` if `[sshWorker]` isn't configured at all, since
there's no SSH connection to run JXA over.

The one exception: "queue behind the current track without interrupting
it" (the non-immediate track-selection range in §7) still goes through
`/remote`'s `queue_next <persistent_id>`, published to a `/remote` topic
under the same base topic. This is a genuine AirPlay-remote queue
operation — Music.app's own "Up Next" queue, which the DACP protocol
manipulates directly — with no equivalent exposed anywhere in Music.app's
AppleScript/JXA scripting dictionary, so there's no direct-control
alternative for this one case.

**Connection lifecycle**: on broker-connect success, subscribes to all
of the above topics and fires a "connection established" notification
(§8.4). On any disconnect (including the very first connect attempt
failing), fires a "connection lost" notification and retries the
connection after a fixed backoff (5 seconds in this implementation),
indefinitely, until the process shuts down. Each process run uses a
distinct MQTT client ID (rather than one fixed ID reused across
restarts) so a not-yet-fully-torn-down previous connection can't cause
the broker to evict a freshly-reconnecting new one — an MQTT spec
behavior (duplicate client IDs get the older connection kicked) that
otherwise becomes a real risk across quick process restarts.

---

## 10. Playlist

An in-memory snapshot of the Mac's Music.app "Jukebox" playlist (the same
playlist the `[sshWorker]` config section's `playlist_name` setting names),
fetched over a persistent SSH link to that Mac (`MusicAppSSHWorker`,
`src/music_app_ssh_worker.py`) rather than read from a bundled file — the
device's filesystem is read-only, so there's no way to keep an on-disk copy
in sync with changes made in Music.app. That same SSH link is also used for
other Mac-side automation not otherwise covered in this document (AirPlay
recovery, now-playing lookups) — see `src/music_app_ssh_worker.py` and
`src/osx/scripts/` for specifics. Each entry has
(at minimum) a name, a numeric index, an artist, and a "persistent ID"
string (matched case-insensitively/uppercased against shairport-sync's own
per-track persistent ID metadata). Fetched once, the first time the SSH
connection comes up (not re-fetched on later reconnects, so a playlist
edited in Music.app after that first fetch won't be picked up without
restarting the jukebox process); a fetch that fails (SSH not yet connected,
scripting error, unparseable output) is silently retried on the next
reconnect. Two lookups are needed:
- by numeric index (used to resolve a 3-digit keypad selection, after
  subtracting the range-dependent offset described in §7, to an actual
  track to queue or immediate-play)
- by persistent ID (used to resolve an incoming "now playing" track back
  to its playlist index, for §8.1's 4-digit display and right-LED logic)

Until the first fetch succeeds (including if `sshWorker` isn't configured
at all, so no fetch is ever attempted), the playlist is treated as absent:
keypad track-selection reports "no match" via §7's "----"/"no playlist
from mac" feedback rather than the standard "Err". `Playlist.from_file()`
(playlist.py) still exists for local development without a reachable Mac —
point it at your own JSON fixture in the same shape
get_playlist_tracks.js returns — but the running app doesn't use it by
default.

---

## 11. Configuration surface

Everything below should be independently configurable (this
implementation uses a single INI-style file), with sensible defaults if
omitted:

| Setting | Default | Meaning |
|---|---|---|
| Song field display order | Title, Artist, Album | Which fields cycle on the label/value display, and in what order (§6.5) |
| Per-display-width animation timing | — | For each physical display width in use (8-char label, 12-char value): delay between characters, delay after a wrapped "page" finishes before showing the next page, delay after a full animation cycle finishes before restarting (only relevant to the always-looping label/value display), delay per segment during segment-reveal, and which character-reveal style (immediate vs. segment) to use — see §6.4 |
| Panel driver selection | — | Which concrete panel driver to use (serial/Arduino, Linux text-protocol, or Linux binary-protocol) and its connection details (serial port + baud, or device path); for the binary driver, also the digit-display reveal's per-segment delay (§6.4) |
| Track-selection feedback | 3 blinks / 250ms phase / "Err" / 2s | §7's post-entry blink/error feedback tuning |
| Paused-display flash interval | 750ms | §8.2 |
| MQTT broker connection | localhost:1883, base topic `shairport-sync` | §9 |
| Remote-control mode | `jxa` | `jxa`/`mqtt`/`fallback` — §9 |
| Fallback trip threshold/window | 3 failures / 300s | Only relevant in `fallback` mode — §9 |
| Playlist file path | bundled default | §10 |

---

## 12. Theory of operation — worked examples

**A new song starts playing.** shairport-sync publishes `track_id`
(different from before) → all previously-known metadata is discarded.
`artist` arrives → known-artist updated. `album` arrives → known-album
updated (no display action yet). `title` arrives → since both artist and
title are now known, a "song changed" event fires with all three fields.
The label/value rotation is rebuilt and interrupts to show the first
field pair (Title, by default field order) immediately. Simultaneously,
the panel's 4-digit display and right LED get looked up (was this
persistent ID found in the local playlist?) and updated to match.

**User types a 3-digit track selection.** First digit press: mode
becomes track-selection, left LED on, right LED off, 4-digit display
echoes "1   " (say). Second and third digits echo similarly, un-animated.
On the third digit: entry ends, left LED off; the 3-digit code is looked
up in the playlist; if found, a `queue_next <persistent_id>` remote
command is published over MQTT and the display blinks the code 3 times;
if not found, "Err" is shown for 2 seconds. Either way, the display then
reverts to whatever the 4-digit display/right-LED were showing before
entry started — the *actual* effect of a successful selection (the new
track becoming "now playing") only becomes visible later, whenever
shairport-sync reports the track actually started, following the "new
song starts playing" flow above.

**Playback is paused from the AirPlay source (or via a `PP` keypad
command).** shairport-sync publishes `play_flush`. The 4-digit display
begins alternating between the current track index and blank every
750ms, un-animated, until either `play_resume` arrives (display returns
to steady) or the session ends entirely via `active_end` (see below).

**The MQTT connection to shairport-sync drops.** A "Problem" / "MQTT
Lost. Attempting Reconnect." message is added to the rotation and shown
immediately (interrupting whatever was on screen), persisting
indefinitely. The client keeps retrying the broker connection every 5
seconds in the background. Once it reconnects, the message is removed.
Note this is orthogonal to shairport-sync's own play state — the AirPlay
audio session itself may still be perfectly healthy the whole time; this
purely reflects *this app's* link to the MQTT broker.

**Nothing has played for a while (broader idle timeout).**
shairport-sync publishes `active_end`. Both panel digit displays clear,
the right LED turns off, and "Playback" / "stopped" replaces whatever
was on the label/value display, shown immediately. As soon as real
playback resumes and a "song changed" event fires again, this status is
dropped from the rotation for good (not just skipped for one lap).
