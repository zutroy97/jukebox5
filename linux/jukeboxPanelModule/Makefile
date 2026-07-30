obj-m += jukebox_panel.o
obj-m += jukebox_panel_bin.o

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD := $(shell pwd)

.PHONY: all clean install load unload load-bin unload-bin

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

# Installs to /lib/modules/$(uname -r)/extra and refreshes module deps so
# `modprobe jukebox_panel` (and modules-load.d autoloading) can find it.
install: all
	$(MAKE) -C $(KDIR) M=$(PWD) modules_install
	depmod -a

# jukebox_panel and jukebox_panel_bin are independent alternatives that
# both claim the same GPIO lines -- never load both at once.
load:
	insmod jukebox_panel.ko

unload:
	rmmod jukebox_panel

load-bin:
	insmod jukebox_panel_bin.ko

unload-bin:
	rmmod jukebox_panel_bin
