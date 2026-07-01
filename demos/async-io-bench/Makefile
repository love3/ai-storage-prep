# Build iobench. io_uring support is auto-detected via the kernel uapi header
# (no liburing needed). POSIX AIO needs -lrt on Linux.
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra
UNAME_S := $(shell uname -s)

LDLIBS := -lpthread
ifeq ($(UNAME_S),Linux)
LDLIBS += -lrt
endif

all: iobench

iobench: iobench.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f iobench *.o
