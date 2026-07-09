obj-m += jukebox_panel.o

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD := $(shell pwd)

.PHONY: all clean install load unload

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

# Installs to /lib/modules/$(uname -r)/extra and refreshes module deps so
# `modprobe jukebox_panel` (and modules-load.d autoloading) can find it.
install: all
	$(MAKE) -C $(KDIR) M=$(PWD) modules_install
	depmod -a

load:
	insmod jukebox_panel.ko

unload:
	rmmod jukebox_panel
