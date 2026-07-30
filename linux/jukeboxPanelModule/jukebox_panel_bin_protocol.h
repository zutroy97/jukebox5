/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Wire protocol for /dev/jukebox_panel_bin, spoken by jukebox_panel_bin.c.
 * This is a separate, standalone alternative to jukebox_panel.c's
 * line-based text protocol -- not an extension of it. Only one of the two
 * modules is ever loaded at a time (they contend for the same GPIO lines).
 *
 * write(): each write() call must supply exactly sizeof(struct
 * jbp_bin_cmd) (8) bytes -- one complete command (struct jbp_bin_cmd
 * below). Any other size is rejected with -EINVAL; there is no
 * partial-write reassembly across calls, so build the whole packet before
 * calling write() (this is how callers naturally use it anyway).
 *
 * read(): a stream of raw 2-byte keypad signatures (__u16, native
 * endianness), one per settled/debounced key change. This is the same raw
 * 16-bit scan code documented in docs/jukeboxHarness.md's keypad protocol
 * section -- the driver does NOT decode it to a character. Translating a
 * signature to '0'-'9'/R/P (or recognizing an unknown one) is entirely the
 * caller's responsibility.
 *
 * All structs are explicitly sized/padded so a userspace caller can mirror
 * them byte-for-byte (e.g. Python struct.pack with native '=' or '<' mode
 * on this little-endian platform) without any compiler-dependent padding
 * surprises.
 */
#ifndef _JUKEBOX_PANEL_BIN_PROTOCOL_H
#define _JUKEBOX_PANEL_BIN_PROTOCOL_H

#ifdef __KERNEL__
#include <linux/types.h>
#else
#include <stdint.h>
typedef uint8_t __u8;
typedef uint32_t __u32;
#endif

/* Selects which digit display a JBP_CMD_SET_INT/JBP_CMD_SET_RAW applies to. */
#define JBP_TARGET_3DIGIT 0
#define JBP_TARGET_4DIGIT 1

/* Selects which LED a JBP_CMD_SET_LED applies to. */
#define JBP_LED_RIGHT 0 /* led0 */
#define JBP_LED_LEFT  1 /* led1 */

/* Display an unsigned decimal integer, right-justified (blank-padded on
 * the left) on the display named by `target`. Value must fit -- 0-999 for
 * JBP_TARGET_3DIGIT, 0-9999 for JBP_TARGET_4DIGIT -- or the command is
 * rejected (write() returns -EINVAL) rather than silently truncating.
 * Preserves the current LED state on the 4-digit display. */
#define JBP_CMD_SET_INT 1

/* Set the display named by `target`'s raw 32-bit shift-register word
 * directly from `value`, bypassing digit/segment translation entirely --
 * see docs/jukeboxHarness.md for the bit layout. For JBP_TARGET_4DIGIT
 * this includes the LED bits (bit 31 = led0, bits 29-30 = led1); the
 * driver's LED state tracking is updated to match whatever bits are set
 * here, so a later JBP_CMD_SET_LED behaves consistently. */
#define JBP_CMD_SET_RAW 2

/* Set led0 or led1 (selected by `target`, JBP_LED_RIGHT/JBP_LED_LEFT)
 * on/off per `value` (0 = off, nonzero = on), leaving display segments
 * untouched. */
#define JBP_CMD_SET_LED 3

/* sizeof == 8: cmd(1) + target(1) + pad(2) + value(4). Fixed size for
 * every command keeps write()'s framing trivial: accumulate exactly
 * sizeof(struct jbp_bin_cmd) bytes, then dispatch on `cmd`. */
struct jbp_bin_cmd {
	__u8  cmd;
	__u8  target;
	__u8  _pad[2];
	__u32 value;
};

#endif /* _JUKEBOX_PANEL_BIN_PROTOCOL_H */
