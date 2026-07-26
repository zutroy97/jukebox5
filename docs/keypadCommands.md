# Keypad commands

Reference list of everything the 12-key panel keypad (`0`–`9`, `P`, `R`)
does. For the full state-machine behavior (timeouts, feedback, LEDs), see
`SPECIFICATION.md` §7 and `src/observers/coordinator.py`'s `_TrackSelector`.

The first key pressed after idle decides the mode: a digit starts
**track selection**, `P` starts a **command**. `R` cancels whatever's in
progress, at any time.

## Track selection (3 digits)

Type exactly 3 digits. The code is interpreted as a playlist index plus an
offset, which one depends on the range:

| Code range | Playlist index | Effect |
| --- | --- | --- |
| `300`–`500` | code − 300 | **Plays immediately** — queued, then skipped to right away (interrupts whatever's currently playing). |
| `100`–`299`, `501`–`999` | code − 100 | Queued behind the current track — starts once it ends, doesn't interrupt. |

A code with no matching playlist track shows `Err` on the 4-digit display
for 2 seconds. A match blinks the code 3 times. (Current playlist has 198
tracks, indices 0–197 — e.g. `305` immediate-plays index 5, `150` queues
index 50.)

Digit entry times out after 10 seconds of inactivity between keystrokes.

## `P`-commands

| Keys | Command | Effect |
| --- | --- | --- |
| `P` `P` | `playpause` | Toggle play/pause on the Mac. If nothing observably happens within `remote_command_timeout_s`, triggers AirPlay recovery over SSH (see `SPECIFICATION.md` / `sshWorker` config). |
| `P` `1` `1` `1` | `previtem` | Previous track. |
| `P` `6` `6` `6` | `nextitem` | Next track. |
| `P` `2` `2` `2` | *(local)* | Skip the alpha display immediately to its next rotation item (artist/title/album or an active status message). Does not touch playback. |
| `P` `9` `1` `1` | *(local)* | Show the Pi's LAN IP address on the alpha display for 30 seconds. |

Commands fire the instant the full sequence is typed — no need to wait
out a timeout — unless the sequence typed so far is also a prefix of a
longer command still in the table above (not currently the case for any
pair here), in which case it resolves after 2 seconds of inactivity if
nothing longer follows. Command entry times out (and cancels silently)
after 2 seconds of inactivity if the sequence doesn't match any full
command and can't extend into one either — e.g. `P4`.

## `R`

Cancels any in-progress digit or command entry and returns to idle,
discarding it. Has no effect when nothing is being entered.
