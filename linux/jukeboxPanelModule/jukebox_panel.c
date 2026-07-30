// SPDX-License-Identifier: GPL-2.0
/*
 * jukebox_panel - Linux replacement for the Arduino JukeboxPanel firmware.
 *
 * Bit-bangs the same shift-register display protocol and matrix-keypad scan
 * that arduino/JukeboxPanel/JukeboxPanel.cpp implements, and exposes
 * /dev/jukebox_panel as a character device using the exact same line-based
 * text protocol the Arduino spoke over serial:
 *
 *   write "w3 <text>\n"   -> write <text> (space-padded/truncated to 3 chars) to the 3-digit display
 *   write "w4 <text>\n"   -> write <text> (space-padded/truncated to 4 chars) to the 4-digit display
 *   write "led0\n" / "led0 1\n" -> right LED off / on
 *   write "led1\n" / "led1 1\n" -> left LED off / on
 *   write "off\n"         -> blank both displays and both LEDs
 *   write "c\n"           -> blank both displays (LEDs untouched)
 *   read  -> blocks until a button is pressed, then returns "BTN:<c>\n"
 *            where <c> is one of 0-9, R, P
 *
 * GPIO pin assignments are placeholders (module parameters) until the panel
 * is wired to this Pi's header -- override them with insmod/modprobe options
 * or by editing /etc/modprobe.d, e.g.:
 *   options jukebox_panel gpio_clock=17 gpio_enable=27 ...
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/miscdevice.h>
#include <linux/uaccess.h>
#include <linux/gpio/consumer.h>
#include <linux/gpio/machine.h>
#include <linux/kfifo.h>
#include <linux/kthread.h>
#include <linux/mutex.h>
#include <linux/wait.h>
#include <linux/delay.h>
#include <linux/ctype.h>
#include <linux/string.h>
#include <linux/poll.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/overflow.h>

#define DEVICE_NAME "jukebox_panel"

/* The gpiochip label for the Pi's SoC GPIO controller. Looked up by name
 * rather than by the legacy global GPIO number, because that number's base
 * offset is assigned dynamically at boot (observed to be 512 on this Pi 3,
 * but it is not guaranteed stable across kernels/boots) -- resolving by
 * (chip label, offset) via a gpiod lookup table sidesteps that entirely. */
#define GPIO_CHIP_LABEL "pinctrl-bcm2835"

/* ------------------------------------------------------------------ */
/* GPIO pin assignments (BCM numbering) -- placeholders, override via   */
/* module parameters once the panel is actually wired to this Pi.       */
/* ------------------------------------------------------------------ */

static int gpio_clock = 17;   /* shift clock, shared by both digit chains, idle high, active-low pulse */
static int gpio_enable = 27;  /* display output-enable / keypad-scan enable, active low */
static int gpio_data4 = 22;   /* serial data in for the 4-digit display chain */
static int gpio_data3 = 23;   /* serial data in for the 3-digit display chain */
static int gpio_matrix_c = 24; /* bit 2 of the keypad scan counter (shares data4/data3 pins for bits 0/1) */
static int gpio_keypad_in0 = 25; /* keypad row input 1 */
static int gpio_keypad_in1 = 5;  /* keypad row input 2 */

module_param(gpio_clock, int, 0444);
MODULE_PARM_DESC(gpio_clock, "BCM GPIO for the display shift clock (placeholder default 17)");
module_param(gpio_enable, int, 0444);
MODULE_PARM_DESC(gpio_enable, "BCM GPIO for display-enable/keypad-scan-enable (placeholder default 27)");
module_param(gpio_data4, int, 0444);
MODULE_PARM_DESC(gpio_data4, "BCM GPIO for the 4-digit display serial data (placeholder default 22)");
module_param(gpio_data3, int, 0444);
MODULE_PARM_DESC(gpio_data3, "BCM GPIO for the 3-digit display serial data (placeholder default 23)");
module_param(gpio_matrix_c, int, 0444);
MODULE_PARM_DESC(gpio_matrix_c, "BCM GPIO for keypad matrix column-select bit 2 (placeholder default 24)");
module_param(gpio_keypad_in0, int, 0444);
MODULE_PARM_DESC(gpio_keypad_in0, "BCM GPIO for keypad row input 0 (placeholder default 25)");
module_param(gpio_keypad_in1, int, 0444);
MODULE_PARM_DESC(gpio_keypad_in1, "BCM GPIO for keypad row input 1 (placeholder default 5)");

/* Post-report lockout duration -- see keypad_scan_thread_fn()'s comment
 * for why this is no longer "how long a key must sit still before being
 * reported" (that's keypad_confirm_ms now). Kept as the same name/default
 * since it still serves the same broad purpose (rejecting switch
 * chatter), just at a different point in the state machine. */
static int keypad_debounce_ms = 50; /* matches JukeboxPanel::GetKey()'s original 50ms settle time */
module_param(keypad_debounce_ms, int, 0644);
MODULE_PARM_DESC(keypad_debounce_ms, "Milliseconds to ignore further signature changes after a press is reported");

/* How long a signature must read consistently before being trusted at
 * all -- just enough to reject single-sample electrical noise, not a full
 * debounce window. See keypad_scan_thread_fn(). */
static int keypad_confirm_ms = 10;
module_param(keypad_confirm_ms, int, 0644);
MODULE_PARM_DESC(keypad_confirm_ms, "Milliseconds a signature must read consistently before being trusted (press or idle)");

/* Safety-net cap on how long the post-report lockout can last waiting for
 * a clean idle read -- see keypad_scan_thread_fn()'s KEYPAD_LOCKED_OUT
 * comment. Must be well above keypad_debounce_ms (the normal-case lockout
 * length) or it would fire before that even elapses. A tap held longer
 * than this will re-fire (loses the "exactly once per press" guarantee
 * for unusually long holds) rather than wedging the whole keypad. */
static int keypad_rearm_timeout_ms = 300;
module_param(keypad_rearm_timeout_ms, int, 0644);
MODULE_PARM_DESC(keypad_rearm_timeout_ms, "Milliseconds after a report to force re-arming even without a confirmed idle read");

static int keypad_scan_period_ms = 5; /* the Arduino scans once per loop() iteration, effectively continuously */
module_param(keypad_scan_period_ms, int, 0644);
MODULE_PARM_DESC(keypad_scan_period_ms, "Milliseconds between keypad scans");

/* Bit-bang timing. The Arduino used delayMicroseconds(400) busy-waits; kept
 * symmetric and conservative here since a Pi CPU is vastly faster than the
 * 16MHz AVR this protocol was designed around. Exposed as a module param
 * (rather than a #define) so the settle time can be tuned from userspace
 * while chasing signal-integrity issues (e.g. a slow level-shifter) without
 * a rebuild for every trial value. */
static int bit_delay_us = 400;
module_param(bit_delay_us, int, 0644);
MODULE_PARM_DESC(bit_delay_us, "Microseconds to hold each display clock phase (default 400)");

/* Was a hardcoded 5us #define; raised to a more generous default and made
 * runtime-tunable (mirroring jukebox_panel_bin.c) after 0xfdff
 * (row-input-1 shorted at scan address 1) was observed settling in and
 * passing keypad_debounce_ms as a phantom event after nearly every real
 * keypress there -- consistent with the level shifter/matrix bus not
 * having fully settled 5us after the address-0->1 transition (the first
 * GPIO edge of the scan, right as data4 flips 0->1) before being sampled.
 * Same scan_keypad_raw() shape here, so the same fix applies. */
static int keypad_settle_us = 50;
module_param(keypad_settle_us, int, 0644);
MODULE_PARM_DESC(keypad_settle_us, "Microseconds to wait after driving a scan address before sampling row inputs (default 50)");

/* ------------------------------------------------------------------ */
/* 7-segment character map, ported verbatim from JukeboxPanel.h        */
/* (index 0-9 = '0'-'9', 10-35 = 'a'-'z')                               */
/* ------------------------------------------------------------------ */

static const u8 jukebox_characters[36] = {
	119, 65, 59, 107, 77, 110, 126, 67, 127, 111,   /* 0-9 */
	95, 124, 54, 121, 62, 30, 111, 92, 20, 113,     /* a-j */
	93, 52, 82, 88, 120, 31, 79, 24, 110, 60,       /* k-t */
	117, 112, 37, 93, 109, 59                       /* u-z */
};

static u8 get_character_map(char c)
{
	if (c == ' ')
		return 0;
	if (c >= '0' && c <= '9')
		return jukebox_characters[c - '0'];
	if (c >= 'a' && c <= 'z')
		return jukebox_characters[c - 'a' + 10];
	if (c >= 'A' && c <= 'Z')
		return jukebox_characters[c - 'A' + 10];
	if (c == '-')
		return 8;
	return 32; /* unmapped -> underscore, matches GetCharacterMap()'s fallback */
}

/* ------------------------------------------------------------------ */
/* Shared display/LED state, and the GPIO bit-bang primitives.          */
/* gpio_mutex serializes all GPIO access: display updates and keypad    */
/* scans both drive gpio_data3/gpio_data4/gpio_matrix_c and must never   */
/* interleave.                                                          */
/* ------------------------------------------------------------------ */

static DEFINE_MUTEX(gpio_mutex);
static u32 display3_line;
static u32 display4_line;
static bool led0_state;
static bool led1_state;

static struct gpio_desc *desc_clock;
static struct gpio_desc *desc_enable;
static struct gpio_desc *desc_data4;
static struct gpio_desc *desc_data3;
static struct gpio_desc *desc_matrix_c;
static struct gpio_desc *desc_keypad_in0;
static struct gpio_desc *desc_keypad_in1;

/* Caller must hold gpio_mutex. */
static void write_bit(int d3, int d4)
{
	gpiod_set_raw_value(desc_data3, d3);
	gpiod_set_raw_value(desc_data4, d4);
	gpiod_set_raw_value(desc_clock, 0);
	udelay(bit_delay_us);
	gpiod_set_raw_value(desc_clock, 1);
	udelay(bit_delay_us);
}

/* Caller must hold gpio_mutex. Shifts display3_line/display4_line out to
 * the hardware. The receiving chips are MM5450/MM5451 LED display drivers:
 * per datasheet, a frame is a start bit ('1') followed by exactly 35 data
 * bits, latched automatically after the 36th clock -- there is no separate
 * load/latch pulse. Our 32-bit display{3,4}_line supplies the first 32 of
 * those 35 bits (LSB first); the remaining 3 are sent as zero filler. */
static void update_display(void)
{
	int i;
	u32 mask;

	gpiod_set_raw_value(desc_enable, 1);
	write_bit(1, 1); /* start */
	udelay(bit_delay_us);

	for (i = 0; i < 32; i++) {
		mask = 1UL << i;
		write_bit((display3_line & mask) ? 1 : 0,
			  (display4_line & mask) ? 1 : 0);
	}

	for (i = 0; i < 3; i++)
		write_bit(0, 0);

	gpiod_set_raw_value(desc_enable, 0);
}

/* Caller must hold gpio_mutex. Packs up to 4 characters of `text` into the
 * given display line MSB-first-per-char after reversing it, mirroring
 * JukeboxPanel::write(). For the 4-digit line, re-applies the LED bits the
 * same way the firmware does (led0 -> bit31, led1 -> bits 29 AND 30). */
static void pack_display_text(const char *text, size_t len, bool is_display4)
{
	u32 display = 0;
	int i;
	char c;

	for (i = 0; i < 4; i++) {
		size_t src_index = len - 1 - i; /* reversed */

		c = (i < len) ? text[src_index] : '\0';
		if (c == '\0')
			break;
		display <<= 7;
		display |= get_character_map(c);
	}

	if (is_display4) {
		if (led0_state)
			display |= 0x80000000;
		if (led1_state)
			display |= 0x60000000;
		display4_line = display;
	} else {
		display3_line = display;
	}
}

/* Caller must hold gpio_mutex. */
static void apply_off(void)
{
	display3_line = 0;
	display4_line = 0;
	led0_state = false;
	led1_state = false;
	update_display();
}

/* Caller must hold gpio_mutex. Mirrors JukeboxPanel::Clear(): blanks both
 * digit displays but leaves LED0/LED1 untouched (display4_line's top 3 bits
 * carry the LED state, mask 0xE0000000 preserves exactly those). */
static void apply_clear(void)
{
	display3_line = 0;
	display4_line &= 0xE0000000;
	update_display();
}

static void apply_led0(bool on)
{
	led0_state = on;
	if (on)
		display4_line |= 0x80000000;
	else
		display4_line &= ~0x80000000U;
	update_display();
}

static void apply_led1(bool on)
{
	led1_state = on;
	if (on)
		display4_line |= 0x60000000;
	else
		display4_line &= ~0x60000000U;
	update_display();
}

/* Caller must hold gpio_mutex. Mirrors JukeboxPanel::getCurrentKeypadValue():
 * drives a 3-bit column-select counter across gpio_data4/gpio_data3/gpio_matrix_c
 * (the same pins the display uses) and samples the two row inputs at each
 * step, assembling a 16-bit raw scan code. */
static u16 scan_keypad_raw(void)
{
	u16 result = 0;
	int i;

	gpiod_set_raw_value(desc_enable, 0);
	for (i = 0; i < 8; i++) {
		gpiod_set_raw_value(desc_data4, i & 0x01);
		gpiod_set_raw_value(desc_data3, i & 0x02);
		gpiod_set_raw_value(desc_matrix_c, i & 0x04);
		udelay(keypad_settle_us);
		if (gpiod_get_raw_value(desc_keypad_in0))
			result |= BIT(i);
		if (gpiod_get_raw_value(desc_keypad_in1))
			result |= BIT(i + 8);
	}

	/* Restore the shared data/select lines to their display-mode idle
	 * level. The loop's last step (i=7) leaves data4/data3/matrix_c all
	 * driven HIGH, and since this scan runs continuously in the
	 * background every keypad_scan_period_ms, that HIGH state (and the
	 * walk through it on every scan) would otherwise bleed onto the
	 * display's data/select bus between/after writes. */
	gpiod_set_raw_value(desc_data4, 0);
	gpiod_set_raw_value(desc_data3, 0);
	gpiod_set_raw_value(desc_matrix_c, 0);

	return result;
}

/* Mirrors JukeboxPanel::GetCurrentKeypadLetter(). '_' means no/unrecognized key. */
static char raw_to_key(u16 raw)
{
	switch (raw) {
	case 0x7dff: return 'P';
	case 0xFDDF: return '1';
	case 0xfcff: return '2';
	case 0xfdf7: return '3';
	case 0xfdfc: return '4';
	case 0xedff: return '5';
	case 0xfdef: return '6';
	case 0xfd3f: return '7';
	case 0xF5FF: return '8';
	case 0xFDFB: return '9';
	case 0xDDFF: return '0';
	case 0xBDFF: return 'R';
	default: return '_';
	}
}

/* ------------------------------------------------------------------ */
/* Button-press event queue: the keypad-scan kthread pushes "BTN:X\n"    */
/* strings here; read() blocks on button_wait until bytes are available. */
/* ------------------------------------------------------------------ */

#define EVENT_FIFO_SIZE 256

static DEFINE_KFIFO(button_fifo, char, EVENT_FIFO_SIZE);
static DEFINE_MUTEX(button_fifo_mutex);
static DECLARE_WAIT_QUEUE_HEAD(button_wait);

static void queue_button_event(char key)
{
	char event[7]; /* "BTN:" + digit/R/P + '\n' = 6 data bytes, +1 for scnprintf's NUL */
	int len = scnprintf(event, sizeof(event), "BTN:%c\n", key);

	mutex_lock(&button_fifo_mutex);
	if (kfifo_avail(&button_fifo) >= len) {
		kfifo_in(&button_fifo, event, len);
		wake_up_interruptible(&button_wait);
	} else {
		pr_warn("jukebox_panel: button event FIFO full, dropping '%c'\n", key);
	}
	mutex_unlock(&button_fifo_mutex);
}

/* Debounce state. Leading-edge/lockout design (changed from an earlier
 * trailing-edge one that required a key to sit perfectly still for
 * keypad_debounce_ms before reporting it): a worn mechanical switch can
 * bounce -- make, break, make again -- across a span longer than that,
 * which a "must-stay-still" window can miss entirely (never accumulates
 * enough continuous stable time, so the tap is silently dropped even
 * though the switch clearly closed). Reporting instead fires as soon as a
 * non-'_' key reads consistently for just keypad_confirm_ms (long enough
 * to reject single-sample electrical noise, short enough that ongoing
 * bounce doesn't reset it back to zero), then all further changes are
 * ignored for keypad_debounce_ms -- covering the rest of that same
 * bounce -- and a new press isn't recognized until the scan reads '_' for
 * keypad_confirm_ms too, confirming the key was actually released. */
static struct task_struct *keypad_thread;

enum keypad_state { KEYPAD_ARMED, KEYPAD_LOCKED_OUT };

static int keypad_scan_thread_fn(void *unused)
{
	enum keypad_state state = KEYPAD_ARMED;
	char last_key = '_';
	unsigned long confirmed_since = jiffies;
	unsigned long lockout_until = jiffies;
	unsigned long rearm_deadline = jiffies;

	while (!kthread_should_stop()) {
		char this_key;
		bool confirmed;

		mutex_lock(&gpio_mutex);
		this_key = raw_to_key(scan_keypad_raw());
		mutex_unlock(&gpio_mutex);

		if (this_key != last_key) {
			last_key = this_key;
			confirmed_since = jiffies;
		}
		confirmed = jiffies_to_msecs(jiffies - confirmed_since) >= keypad_confirm_ms;

		switch (state) {
		case KEYPAD_ARMED:
			if (this_key != '_' && confirmed) {
				queue_button_event(this_key);
				state = KEYPAD_LOCKED_OUT;
				lockout_until = jiffies + msecs_to_jiffies(keypad_debounce_ms);
				rearm_deadline = jiffies + msecs_to_jiffies(keypad_rearm_timeout_ms);
			}
			break;
		case KEYPAD_LOCKED_OUT:
			/* Prefer re-arming on a clean, confirmed idle read (the
			 * common case for a normal tap) -- but never wait past
			 * rearm_deadline for one. Verified against real hardware
			 * (jukebox_panel_bin.c, this driver's sibling) that a line
			 * noisy enough to never sit still for confirm_ms on its
			 * own can otherwise wedge the state machine in
			 * KEYPAD_LOCKED_OUT permanently. */
			if (!time_after_eq(jiffies, lockout_until))
				break;
			if ((this_key == '_' && confirmed) ||
			    time_after_eq(jiffies, rearm_deadline))
				state = KEYPAD_ARMED;
			break;
		}

		msleep_interruptible(keypad_scan_period_ms);
	}

	return 0;
}

/* ------------------------------------------------------------------ */
/* write(): line-based command parser                                   */
/* ------------------------------------------------------------------ */

#define LINE_BUF_SIZE 64

static char line_buf[LINE_BUF_SIZE];
static size_t line_buf_len;
static DEFINE_MUTEX(write_mutex);

static void process_line(char *line)
{
	char *cmd, *arg;

	/* Strip a trailing \r left over from \r\n framing. */
	size_t len = strlen(line);

	if (len > 0 && line[len - 1] == '\r')
		line[len - 1] = '\0';

	cmd = strim(line);
	arg = strchr(cmd, ' ');
	if (arg) {
		*arg = '\0';
		arg = strim(arg + 1);
	}

	mutex_lock(&gpio_mutex);

	if (!strcmp(cmd, "w3")) {
		if (arg)
			pack_display_text(arg, strlen(arg), false);
		else
			display3_line = 0;
		update_display();
	} else if (!strcmp(cmd, "w4")) {
		pack_display_text(arg ? arg : "", arg ? strlen(arg) : 0, true);
		update_display();
	} else if (!strcmp(cmd, "c")) {
		apply_clear();
	} else if (!strcmp(cmd, "led0")) {
		apply_led0(arg != NULL);
	} else if (!strcmp(cmd, "led1")) {
		apply_led1(arg != NULL);
	} else if (!strcmp(cmd, "off")) {
		apply_off();
	} else if (strlen(cmd) > 0) {
		pr_debug("jukebox_panel: ignoring unknown command '%s'\n", cmd);
	}

	mutex_unlock(&gpio_mutex);
}

static ssize_t jukebox_write(struct file *filp, const char __user *buf, size_t count, loff_t *ppos)
{
	char chunk[LINE_BUF_SIZE];
	size_t to_copy = min(count, sizeof(chunk));
	size_t i;

	if (copy_from_user(chunk, buf, to_copy))
		return -EFAULT;

	mutex_lock(&write_mutex);
	for (i = 0; i < to_copy; i++) {
		if (chunk[i] == '\n') {
			line_buf[line_buf_len] = '\0';
			process_line(line_buf);
			line_buf_len = 0;
			continue;
		}

		if (line_buf_len >= LINE_BUF_SIZE - 1) {
			pr_warn("jukebox_panel: input line overflow, discarding\n");
			line_buf_len = 0;
			continue;
		}

		line_buf[line_buf_len++] = chunk[i];
	}
	mutex_unlock(&write_mutex);

	return count;
}

/* ------------------------------------------------------------------ */
/* read(): blocks until a button-press event is queued                  */
/* ------------------------------------------------------------------ */

static ssize_t jukebox_read(struct file *filp, char __user *buf, size_t count, loff_t *ppos)
{
	unsigned int copied;
	int ret;

	/* Looping instead of returning after one wait/copy pair matters with
	 * more than one reader open on this device: two readers can both wake
	 * from wait_event_interruptible when an event arrives, but only one
	 * wins the race to actually drain it via kfifo_to_user below. Without
	 * the loop, the loser would copy 0 bytes and return 0 -- which read()
	 * callers universally treat as EOF, causing e.g. `cat` to exit cleanly
	 * as if the stream had ended, even though this driver never actually
	 * signals EOF. Looping back to wait again produces the correct
	 * behavior: keep blocking until this reader gets a real event. */
	do {
		if (kfifo_is_empty(&button_fifo)) {
			if (filp->f_flags & O_NONBLOCK)
				return -EAGAIN;
			ret = wait_event_interruptible(button_wait, !kfifo_is_empty(&button_fifo));
			if (ret)
				return ret;
		}

		mutex_lock(&button_fifo_mutex);
		ret = kfifo_to_user(&button_fifo, buf, count, &copied);
		mutex_unlock(&button_fifo_mutex);

		if (ret)
			return ret;
	} while (copied == 0);

	return copied;
}

/* Clears any events left over from before this open() -- e.g. a signature
 * that settled and got queued right as a previous reader exited (a
 * `timeout`-killed test run, say) without ever reading it, which would
 * otherwise surface as a phantom event firing immediately on the next
 * open with no explanation. With more than one concurrent reader (see
 * jukebox_read()'s comment above), a later open() also clears events an
 * already-open earlier reader hasn't consumed yet -- an accepted tradeoff
 * for this device's actual usage (normally exactly one long-lived reader)
 * in exchange for every open() starting from a known-clean state. */
static int jukebox_open(struct inode *inode, struct file *filp)
{
	mutex_lock(&button_fifo_mutex);
	kfifo_reset(&button_fifo);
	mutex_unlock(&button_fifo_mutex);
	return 0;
}

/* Without this, select()/poll() on the fd always report "ready" (the VFS
 * default when a driver has no .poll op), which would spin userspace readers
 * in a busy loop instead of actually blocking. */
static __poll_t jukebox_poll(struct file *filp, poll_table *wait)
{
	__poll_t mask = EPOLLOUT | EPOLLWRNORM; /* write() never blocks */

	poll_wait(filp, &button_wait, wait);
	if (!kfifo_is_empty(&button_fifo))
		mask |= EPOLLIN | EPOLLRDNORM;

	return mask;
}

static const struct file_operations jukebox_fops = {
	.owner = THIS_MODULE,
	.open = jukebox_open,
	.write = jukebox_write,
	.read = jukebox_read,
	.poll = jukebox_poll,
	.llseek = noop_llseek,
};

static struct miscdevice jukebox_miscdev = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = DEVICE_NAME,
	.fops = &jukebox_fops,
	.mode = 0660,
};

/* ------------------------------------------------------------------ */
/* Module init/exit                                                     */
/* ------------------------------------------------------------------ */

#define PIN_COUNT 7

struct gpio_pin_setup {
	int *bcm_pin;
	const char *con_id;
	struct gpio_desc **desc;
	enum gpiod_flags flags;
};

static struct gpio_pin_setup pin_setups[PIN_COUNT] = {
	{ &gpio_clock, "clock", &desc_clock, GPIOD_OUT_HIGH }, /* idle high, active-low pulse */
	{ &gpio_enable, "enable", &desc_enable, GPIOD_OUT_LOW },
	{ &gpio_data4, "data4", &desc_data4, GPIOD_OUT_LOW },
	{ &gpio_data3, "data3", &desc_data3, GPIOD_OUT_LOW },
	{ &gpio_matrix_c, "matrix-c", &desc_matrix_c, GPIOD_OUT_LOW },
	{ &gpio_keypad_in0, "keypad-in0", &desc_keypad_in0, GPIOD_IN },
	{ &gpio_keypad_in1, "keypad-in1", &desc_keypad_in1, GPIOD_IN },
};

static struct gpiod_lookup_table *jukebox_lookup;

/* Builds a gpiod lookup table resolving each pin by (chip label, offset)
 * rather than a legacy global GPIO number, then acquires every descriptor.
 * See the GPIO_CHIP_LABEL comment above for why. */
static int request_all_gpios(void)
{
	size_t i;
	int ret;

	jukebox_lookup = kzalloc(struct_size(jukebox_lookup, table, PIN_COUNT + 1), GFP_KERNEL);
	if (!jukebox_lookup)
		return -ENOMEM;

	jukebox_lookup->dev_id = NULL; /* match by con_id alone; no associated struct device */
	for (i = 0; i < PIN_COUNT; i++) {
		jukebox_lookup->table[i] = (struct gpiod_lookup) {
			.key = GPIO_CHIP_LABEL,
			.chip_hwnum = *pin_setups[i].bcm_pin,
			.con_id = pin_setups[i].con_id,
			.idx = 0,
			.flags = GPIO_ACTIVE_HIGH,
		};
	}
	/* table[PIN_COUNT] is left zeroed by kzalloc as the required sentinel. */

	gpiod_add_lookup_table(jukebox_lookup);

	for (i = 0; i < PIN_COUNT; i++) {
		*pin_setups[i].desc = gpiod_get_index(NULL, pin_setups[i].con_id, 0, pin_setups[i].flags);
		if (IS_ERR(*pin_setups[i].desc)) {
			ret = PTR_ERR(*pin_setups[i].desc);
			pr_err("jukebox_panel: failed to get GPIO '%s' (BCM %d): %d\n",
			       pin_setups[i].con_id, *pin_setups[i].bcm_pin, ret);
			*pin_setups[i].desc = NULL;
			goto unwind;
		}
	}

	return 0;

unwind:
	for (i = 0; i < PIN_COUNT; i++) {
		if (*pin_setups[i].desc) {
			gpiod_put(*pin_setups[i].desc);
			*pin_setups[i].desc = NULL;
		}
	}
	gpiod_remove_lookup_table(jukebox_lookup);
	kfree(jukebox_lookup);
	jukebox_lookup = NULL;
	return ret;
}

static void free_all_gpios(void)
{
	size_t i;

	for (i = 0; i < PIN_COUNT; i++) {
		if (*pin_setups[i].desc) {
			gpiod_put(*pin_setups[i].desc);
			*pin_setups[i].desc = NULL;
		}
	}
	if (jukebox_lookup) {
		gpiod_remove_lookup_table(jukebox_lookup);
		kfree(jukebox_lookup);
		jukebox_lookup = NULL;
	}
}

static int __init jukebox_panel_init(void)
{
	int ret;

	ret = request_all_gpios();
	if (ret)
		return ret;

	mutex_lock(&gpio_mutex);
	apply_off();
	mutex_unlock(&gpio_mutex);

	keypad_thread = kthread_run(keypad_scan_thread_fn, NULL, "jukebox_panel_keypad");
	if (IS_ERR(keypad_thread)) {
		ret = PTR_ERR(keypad_thread);
		pr_err("jukebox_panel: failed to start keypad scan thread: %d\n", ret);
		goto err_free_gpios;
	}

	ret = misc_register(&jukebox_miscdev);
	if (ret) {
		pr_err("jukebox_panel: failed to register /dev/%s: %d\n", DEVICE_NAME, ret);
		goto err_stop_thread;
	}

	pr_info("jukebox_panel: registered /dev/%s (clock=%d enable=%d data4=%d data3=%d matrix_c=%d in0=%d in1=%d)\n",
		DEVICE_NAME, gpio_clock, gpio_enable, gpio_data4, gpio_data3,
		gpio_matrix_c, gpio_keypad_in0, gpio_keypad_in1);
	return 0;

err_stop_thread:
	kthread_stop(keypad_thread);
err_free_gpios:
	free_all_gpios();
	return ret;
}

static void __exit jukebox_panel_exit(void)
{
	misc_deregister(&jukebox_miscdev);
	kthread_stop(keypad_thread);

	mutex_lock(&gpio_mutex);
	apply_off();
	mutex_unlock(&gpio_mutex);

	free_all_gpios();
	pr_info("jukebox_panel: unloaded\n");
}

module_init(jukebox_panel_init);
module_exit(jukebox_panel_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("jukebox5");
MODULE_DESCRIPTION("Linux GPIO driver mimicking the Arduino JukeboxPanel firmware, exposing /dev/jukebox_panel");
