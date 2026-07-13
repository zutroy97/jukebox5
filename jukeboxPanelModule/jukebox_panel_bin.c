// SPDX-License-Identifier: GPL-2.0
/*
 * jukebox_panel_bin - Standalone binary-protocol alternative to
 * jukebox_panel.c, exposing /dev/jukebox_panel_bin instead of
 * /dev/jukebox_panel. This is a separate, independently-loadable module,
 * not an extension of the text-protocol driver -- only one of the two is
 * ever loaded at a time, since both contend for the same GPIO lines. See
 * jukebox_panel_bin_protocol.h for the exact wire format.
 *
 *   write() -> exactly sizeof(struct jbp_bin_cmd) (8) bytes per call, one
 *              command: display an integer right-justified, set a
 *              display's raw 32-bit segment word directly, or set an LED.
 *   read()  -> a stream of raw 2-byte keypad signatures (__u16, native
 *              endianness), one per settled/debounced key change. This
 *              driver does NOT decode a signature to a character -- that
 *              translation is entirely the caller's responsibility.
 *
 * GPIO pin assignments, bit-bang timing, and keypad-scan mechanics are
 * ported verbatim from jukebox_panel.c's currently-working configuration
 * (see docs/displayCorruptionInvestigation.md for why this specific
 * timing -- notably write_bit()'s dwell after the clock's rising edge --
 * matters on this board's current wiring).
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
#include <linux/string.h>
#include <linux/poll.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/overflow.h>

#include "jukebox_panel_bin_protocol.h"

#define DEVICE_NAME "jukebox_panel_bin"

/* See jukebox_panel.c for why this is looked up by (chip label, offset)
 * rather than a legacy global GPIO number. */
#define GPIO_CHIP_LABEL "pinctrl-bcm2835"

/* ------------------------------------------------------------------ */
/* GPIO pin assignments (BCM numbering) -- same defaults as              */
/* jukebox_panel.c, since it's the same physical hardware.               */
/* ------------------------------------------------------------------ */

static int gpio_clock = 17;
static int gpio_enable = 27;
static int gpio_data4 = 22;
static int gpio_data3 = 23;
static int gpio_matrix_c = 24;
static int gpio_keypad_in0 = 25;
static int gpio_keypad_in1 = 5;

module_param(gpio_clock, int, 0444);
MODULE_PARM_DESC(gpio_clock, "BCM GPIO for the display shift clock (default 17)");
module_param(gpio_enable, int, 0444);
MODULE_PARM_DESC(gpio_enable, "BCM GPIO for display-enable/keypad-scan-enable (default 27)");
module_param(gpio_data4, int, 0444);
MODULE_PARM_DESC(gpio_data4, "BCM GPIO for the 4-digit display serial data (default 22)");
module_param(gpio_data3, int, 0444);
MODULE_PARM_DESC(gpio_data3, "BCM GPIO for the 3-digit display serial data (default 23)");
module_param(gpio_matrix_c, int, 0444);
MODULE_PARM_DESC(gpio_matrix_c, "BCM GPIO for keypad matrix column-select bit 2 (default 24)");
module_param(gpio_keypad_in0, int, 0444);
MODULE_PARM_DESC(gpio_keypad_in0, "BCM GPIO for keypad row input 0 (default 25)");
module_param(gpio_keypad_in1, int, 0444);
MODULE_PARM_DESC(gpio_keypad_in1, "BCM GPIO for keypad row input 1 (default 5)");

static int keypad_debounce_ms = 50;
module_param(keypad_debounce_ms, int, 0644);
MODULE_PARM_DESC(keypad_debounce_ms, "Milliseconds a key must be stable before it is reported");

static int keypad_scan_period_ms = 5;
module_param(keypad_scan_period_ms, int, 0644);
MODULE_PARM_DESC(keypad_scan_period_ms, "Milliseconds between keypad scans");

static int bit_delay_us = 400;
module_param(bit_delay_us, int, 0644);
MODULE_PARM_DESC(bit_delay_us, "Microseconds to hold each display clock phase (default 400)");

#define KEYPAD_SETTLE_US 5

/* ------------------------------------------------------------------ */
/* 7-segment digit map, ported verbatim from jukebox_panel.c's           */
/* jukebox_characters[0-9] (indices 10-35 for a-z are irrelevant here    */
/* since this protocol only ever displays decimal integers).            */
/* ------------------------------------------------------------------ */

static const u8 digit_segments[10] = {
	119, 65, 59, 107, 77, 110, 126, 67, 127, 111,
};

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
 * the hardware: a start bit, 32 data bits LSB-first, then 3 zero filler
 * bits (36 clocks total) -- see jukebox_panel.c for the full framing
 * rationale, identical here since it's the same receiving chips. */
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

/* Caller must hold gpio_mutex. Renders `value` right-justified
 * (blank-padded on the left, matching the text protocol's "w3 <num>"/
 * "w4 <num>" convention of str(num).rjust(width)) into display3_line or
 * display4_line. Rejects values that don't fit rather than truncating.
 * Preserves the current LED state on the 4-digit display. Returns 0 on
 * success, -EINVAL if `value` doesn't fit in `digit_count` digits. */
static int pack_int_display(u32 value, int digit_count, bool is_display4)
{
	u32 display = 0;
	u32 max_value = 1;
	u32 v = value;
	u8 digits[4]; /* least-significant place first: digits[0] = ones */
	int n_significant;
	int i;

	for (i = 0; i < digit_count; i++)
		max_value *= 10;
	if (value >= max_value)
		return -EINVAL;

	for (i = 0; i < digit_count; i++) {
		digits[i] = v % 10;
		v /= 10;
	}

	/* How many least-significant places are real digits vs. blank
	 * right-justify padding -- always at least 1, so value=0 still
	 * renders as a single '0' rather than going fully blank. */
	n_significant = 1;
	for (i = digit_count - 1; i > 0; i--) {
		if (digits[i] != 0) {
			n_significant = i + 1;
			break;
		}
	}

	/* Process least-significant place first so the most-significant
	 * (leftmost) place is OR'd in last -- landing in the final lowest
	 * 7 bits, exactly matching pack_display_text()'s convention where
	 * the leftmost/most-significant character ends up first-shifted-
	 * out / lowest bits (see jukebox_panel.c). Getting this backwards
	 * either mis-justifies or fully reverses the digit order. */
	for (i = 0; i < digit_count; i++) {
		u8 segments = (i < n_significant) ? digit_segments[digits[i]] : 0;

		display <<= 7;
		display |= segments;
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

	return 0;
}

/* Caller must hold gpio_mutex. Sets a display's raw 32-bit shift word
 * directly, bypassing digit translation. For the 4-digit display this
 * includes the LED bits, so led0_state/led1_state are updated to match
 * whatever was just set -- keeping a later JBP_CMD_SET_LED consistent
 * with what SET_RAW put there. */
static void apply_raw(u32 value, bool is_display4)
{
	if (is_display4) {
		display4_line = value;
		led0_state = (value & 0x80000000) != 0;
		led1_state = (value & 0x60000000) == 0x60000000;
	} else {
		display3_line = value;
	}
}

static void apply_led0(bool on)
{
	led0_state = on;
	if (on)
		display4_line |= 0x80000000;
	else
		display4_line &= ~0x80000000U;
}

static void apply_led1(bool on)
{
	led1_state = on;
	if (on)
		display4_line |= 0x60000000;
	else
		display4_line &= ~0x60000000U;
}

/* Caller must hold gpio_mutex. Mirrors jukebox_panel.c's
 * scan_keypad_raw() exactly: drives a 3-bit column-select counter across
 * gpio_data4/gpio_data3/gpio_matrix_c (the same pins the display uses)
 * and samples the two row inputs at each step, assembling a 16-bit raw
 * scan code. See docs/jukeboxHarness.md for the signature table -- this
 * driver deliberately does not decode it. */
static u16 scan_keypad_raw(void)
{
	u16 result = 0;
	int i;

	gpiod_set_raw_value(desc_enable, 0);
	for (i = 0; i < 8; i++) {
		gpiod_set_raw_value(desc_data4, i & 0x01);
		gpiod_set_raw_value(desc_data3, i & 0x02);
		gpiod_set_raw_value(desc_matrix_c, i & 0x04);
		udelay(KEYPAD_SETTLE_US);
		if (gpiod_get_raw_value(desc_keypad_in0))
			result |= BIT(i);
		if (gpiod_get_raw_value(desc_keypad_in1))
			result |= BIT(i + 8);
	}

	/* Restore the shared data/select lines to their display-mode idle
	 * level -- see jukebox_panel.c's scan_keypad_raw() for why. */
	gpiod_set_raw_value(desc_data4, 0);
	gpiod_set_raw_value(desc_data3, 0);
	gpiod_set_raw_value(desc_matrix_c, 0);

	return result;
}

/* The scan code with no key pressed: every matrix contact open, so both
 * row inputs read high at every scan step. Used only as the debounce
 * state machine's "idle" sentinel below -- never interpreted as meaning
 * any particular key. */
#define KEYPAD_IDLE_RAW 0xFFFF

/* ------------------------------------------------------------------ */
/* Button-press event queue: the keypad-scan kthread pushes raw 16-bit   */
/* signatures here; read() blocks on button_wait until one is available.*/
/* ------------------------------------------------------------------ */

#define EVENT_FIFO_SIZE 128 /* elements (u16), not bytes */

static DEFINE_KFIFO(button_fifo, u16, EVENT_FIFO_SIZE);
static DEFINE_MUTEX(button_fifo_mutex);
static DECLARE_WAIT_QUEUE_HEAD(button_wait);

static void queue_button_event(u16 raw)
{
	mutex_lock(&button_fifo_mutex);
	if (kfifo_avail(&button_fifo) >= 1) {
		kfifo_in(&button_fifo, &raw, 1);
		wake_up_interruptible(&button_wait);
	} else {
		pr_warn("jukebox_panel_bin: button event FIFO full, dropping 0x%04x\n", raw);
	}
	mutex_unlock(&button_fifo_mutex);
}

/* Debounce state, mirroring jukebox_panel.c's keypad_scan_thread_fn()
 * exactly, just operating on the raw signature instead of a decoded
 * character: a signature must read the same non-idle value continuously
 * for keypad_debounce_ms before it is reported, and is reported exactly
 * once per press (not repeated while held). */
static struct task_struct *keypad_thread;

static int keypad_scan_thread_fn(void *unused)
{
	u16 last_raw = KEYPAD_IDLE_RAW;
	u16 last_sent = KEYPAD_IDLE_RAW;
	unsigned long stable_since = jiffies;

	while (!kthread_should_stop()) {
		u16 this_raw;

		mutex_lock(&gpio_mutex);
		this_raw = scan_keypad_raw();
		mutex_unlock(&gpio_mutex);

		if (this_raw != last_raw) {
			last_raw = this_raw;
			stable_since = jiffies;
		} else if (jiffies_to_msecs(jiffies - stable_since) > keypad_debounce_ms) {
			if (this_raw != KEYPAD_IDLE_RAW && this_raw != last_sent)
				queue_button_event(this_raw);
			last_sent = this_raw;
		}

		msleep_interruptible(keypad_scan_period_ms);
	}

	return 0;
}

/* ------------------------------------------------------------------ */
/* write(): one fixed-size binary command per call                      */
/* ------------------------------------------------------------------ */

static int process_cmd(const struct jbp_bin_cmd *c)
{
	int ret = 0;

	mutex_lock(&gpio_mutex);

	switch (c->cmd) {
	case JBP_CMD_SET_INT:
		if (c->target == JBP_TARGET_3DIGIT)
			ret = pack_int_display(c->value, 3, false);
		else if (c->target == JBP_TARGET_4DIGIT)
			ret = pack_int_display(c->value, 4, true);
		else
			ret = -EINVAL;
		if (!ret)
			update_display();
		break;

	case JBP_CMD_SET_RAW:
		if (c->target == JBP_TARGET_3DIGIT) {
			apply_raw(c->value, false);
		} else if (c->target == JBP_TARGET_4DIGIT) {
			apply_raw(c->value, true);
		} else {
			ret = -EINVAL;
			break;
		}
		update_display();
		break;

	case JBP_CMD_SET_LED:
		if (c->target == JBP_LED_RIGHT)
			apply_led0(c->value != 0);
		else if (c->target == JBP_LED_LEFT)
			apply_led1(c->value != 0);
		else {
			ret = -EINVAL;
			break;
		}
		update_display();
		break;

	default:
		ret = -EINVAL;
		break;
	}

	mutex_unlock(&gpio_mutex);
	return ret;
}

static ssize_t jukebox_write(struct file *filp, const char __user *buf, size_t count, loff_t *ppos)
{
	struct jbp_bin_cmd cmd;
	int ret;

	/* Each write() is exactly one command -- no partial-write
	 * reassembly across calls, matching how callers naturally build
	 * one packet and write() it in a single syscall. */
	if (count != sizeof(cmd))
		return -EINVAL;

	if (copy_from_user(&cmd, buf, sizeof(cmd)))
		return -EFAULT;

	ret = process_cmd(&cmd);
	if (ret)
		return ret;

	return sizeof(cmd);
}

/* ------------------------------------------------------------------ */
/* read(): blocks until a keypad signature is queued                    */
/* ------------------------------------------------------------------ */

static ssize_t jukebox_read(struct file *filp, char __user *buf, size_t count, loff_t *ppos)
{
	unsigned int copied;
	int ret;

	/* Loops instead of returning after one wait/copy pair for the same
	 * reason as jukebox_panel.c's jukebox_read(): with more than one
	 * reader open, the loser of the race to drain a just-arrived event
	 * would otherwise see a spurious 0-byte "EOF" read. */
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
			pr_err("jukebox_panel_bin: failed to get GPIO '%s' (BCM %d): %d\n",
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

static int __init jukebox_panel_bin_init(void)
{
	int ret;

	ret = request_all_gpios();
	if (ret)
		return ret;

	mutex_lock(&gpio_mutex);
	display3_line = 0;
	display4_line = 0;
	led0_state = false;
	led1_state = false;
	update_display();
	mutex_unlock(&gpio_mutex);

	keypad_thread = kthread_run(keypad_scan_thread_fn, NULL, "jukebox_panel_bin_keypad");
	if (IS_ERR(keypad_thread)) {
		ret = PTR_ERR(keypad_thread);
		pr_err("jukebox_panel_bin: failed to start keypad scan thread: %d\n", ret);
		goto err_free_gpios;
	}

	ret = misc_register(&jukebox_miscdev);
	if (ret) {
		pr_err("jukebox_panel_bin: failed to register /dev/%s: %d\n", DEVICE_NAME, ret);
		goto err_stop_thread;
	}

	pr_info("jukebox_panel_bin: registered /dev/%s (clock=%d enable=%d data4=%d data3=%d matrix_c=%d in0=%d in1=%d)\n",
		DEVICE_NAME, gpio_clock, gpio_enable, gpio_data4, gpio_data3,
		gpio_matrix_c, gpio_keypad_in0, gpio_keypad_in1);
	return 0;

err_stop_thread:
	kthread_stop(keypad_thread);
err_free_gpios:
	free_all_gpios();
	return ret;
}

static void __exit jukebox_panel_bin_exit(void)
{
	misc_deregister(&jukebox_miscdev);
	kthread_stop(keypad_thread);

	mutex_lock(&gpio_mutex);
	display3_line = 0;
	display4_line = 0;
	update_display();
	mutex_unlock(&gpio_mutex);

	free_all_gpios();
	pr_info("jukebox_panel_bin: unloaded\n");
}

module_init(jukebox_panel_bin_init);
module_exit(jukebox_panel_bin_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("jukebox5");
MODULE_DESCRIPTION("Binary-protocol alternative to jukebox_panel.c, exposing /dev/jukebox_panel_bin");
