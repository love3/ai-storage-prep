/*
 * iobench.c -- a tiny async-I/O micro-benchmark.
 *
 * Compares I/O engines doing random block reads at a target queue depth,
 * reporting IOPS, bandwidth, and latency percentiles (see kb/09).
 *
 *   Engines:
 *     sync      : blocking pread(), effective QD = 1
 *     threads   : N pthreads each doing blocking pread (QD via concurrency)
 *     posixaio  : POSIX aio_read() keeping QD outstanding   (Linux + macOS)
 *     iouring   : Linux io_uring via RAW syscalls (no liburing needed)
 *
 * io_uring is implemented with the kernel uapi header <linux/io_uring.h> and
 * mmap'd SQ/CQ rings -- exactly the architecture described in kb/02.
 *
 * Build:   make            (auto-detects io_uring support)
 * Usage:   ./iobench --file F --engine iouring --qd 32 --bs 4096 --ios 200000
 *          ./iobench --file F --engine iouring --qd 32 --direct
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>
#include <pthread.h>
#include <aio.h>

#if defined(__linux__)
#include <sys/mman.h>
#include <sys/syscall.h>
/* Kernel uapi header ships with linux-glibc-devel; io_uring via raw syscalls,
 * no liburing required. Disable with -DNO_IOURING if your headers lack it. */
#if !defined(NO_IOURING)
#include <linux/io_uring.h>
#define HAVE_IOURING 1
#endif
#endif

/* ------------------------------------------------------------------ utils */
static double now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1e9 + (double)ts.tv_nsec;
}

static int cmp_double(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

typedef struct {
    const char *engine;
    long ios;
    int bs;
    int qd;
    int threads;
    int direct;
    double *lat_us;   /* per-IO latency samples (us) */
    long   nlat;
} Config;

static off_t file_blocks;

static off_t rand_offset(int bs) {
    /* random block-aligned offset within the file */
    off_t blk = (off_t)((double)rand() / ((double)RAND_MAX + 1) * (double)file_blocks);
    return blk * bs;
}

static void report(Config *c, double wall_us) {
    qsort(c->lat_us, c->nlat, sizeof(double), cmp_double);
    double sum = 0;
    for (long i = 0; i < c->nlat; i++) sum += c->lat_us[i];
    double avg = c->nlat ? sum / c->nlat : 0;
    double p50 = c->nlat ? c->lat_us[(long)(0.50 * c->nlat)] : 0;
    double p99 = c->nlat ? c->lat_us[(long)(0.99 * c->nlat)] : 0;
    double p999 = c->nlat ? c->lat_us[(long)(0.999 * c->nlat)] : 0;
    double secs = wall_us / 1e6;
    double iops = secs > 0 ? c->ios / secs : 0;
    double mbps = iops * c->bs / (1024.0 * 1024.0);
    /* machine-parseable: engine,qd,bs,ios,iops,MBps,avg_us,p50,p99,p999 */
    printf("RESULT,%s,%d,%d,%ld,%.0f,%.1f,%.2f,%.2f,%.2f,%.2f\n",
           c->engine, c->qd, c->bs, c->ios, iops, mbps, avg, p50, p99, p999);
}

/* ------------------------------------------------------------------ sync */
static int run_sync(int fd, Config *c) {
    void *buf;
    if (posix_memalign(&buf, 4096, c->bs)) return -1;
    for (long i = 0; i < c->ios; i++) {
        double t0 = now_ns();
        ssize_t r = pread(fd, buf, c->bs, rand_offset(c->bs));
        double t1 = now_ns();
        if (r < 0) { perror("pread"); free(buf); return -1; }
        c->lat_us[c->nlat++] = (t1 - t0) / 1e3;
    }
    free(buf);
    return 0;
}

/* --------------------------------------------------------------- threads */
typedef struct { int fd; Config *c; long ios; long base; } TArg;
static void *tworker(void *arg) {
    TArg *a = (TArg *)arg;
    void *buf;
    if (posix_memalign(&buf, 4096, a->c->bs)) return NULL;
    for (long i = 0; i < a->ios; i++) {
        double t0 = now_ns();
        ssize_t r = pread(a->fd, buf, a->c->bs, rand_offset(a->c->bs));
        double t1 = now_ns();
        if (r < 0) { perror("pread"); break; }
        a->c->lat_us[a->base + i] = (t1 - t0) / 1e3;
    }
    free(buf);
    return NULL;
}
static int run_threads(int fd, Config *c) {
    int n = c->threads > 0 ? c->threads : c->qd;
    pthread_t th[256];
    TArg args[256];
    if (n > 256) n = 256;
    long per = c->ios / n;
    c->nlat = per * n;
    for (int i = 0; i < n; i++) {
        args[i] = (TArg){ fd, c, per, (long)i * per };
        pthread_create(&th[i], NULL, tworker, &args[i]);
    }
    for (int i = 0; i < n; i++) pthread_join(th[i], NULL);
    return 0;
}

/* -------------------------------------------------------------- posixaio */
static int run_posixaio(int fd, Config *c) {
    int qd = c->qd;
    struct aiocb *cbs = calloc(qd, sizeof(*cbs));
    void **bufs = calloc(qd, sizeof(void *));
    double *start = calloc(qd, sizeof(double));
    for (int i = 0; i < qd; i++)
        if (posix_memalign(&bufs[i], 4096, c->bs)) return -1;

    long submitted = 0, completed = 0;
    /* prime the queue */
    for (int i = 0; i < qd && submitted < c->ios; i++) {
        memset(&cbs[i], 0, sizeof(cbs[i]));
        cbs[i].aio_fildes = fd; cbs[i].aio_buf = bufs[i];
        cbs[i].aio_nbytes = c->bs; cbs[i].aio_offset = rand_offset(c->bs);
        start[i] = now_ns();
        if (aio_read(&cbs[i]) < 0) { perror("aio_read"); return -1; }
        submitted++;
    }
    while (completed < c->ios) {
        const struct aiocb *list[256];
        int active = 0; int idx[256];
        for (int i = 0; i < qd; i++)
            if (cbs[i].aio_fildes == fd && start[i] > 0) { list[active] = &cbs[i]; idx[active] = i; active++; }
        if (active == 0) break;
        aio_suspend(list, active, NULL);
        for (int k = 0; k < active; k++) {
            int i = idx[k];
            int e = aio_error(&cbs[i]);
            if (e == EINPROGRESS) continue;
            aio_return(&cbs[i]);
            c->lat_us[c->nlat++] = (now_ns() - start[i]) / 1e3;
            completed++;
            start[i] = 0;
            if (submitted < c->ios) {           /* refill to keep QD */
                memset(&cbs[i], 0, sizeof(cbs[i]));
                cbs[i].aio_fildes = fd; cbs[i].aio_buf = bufs[i];
                cbs[i].aio_nbytes = c->bs; cbs[i].aio_offset = rand_offset(c->bs);
                start[i] = now_ns();
                if (aio_read(&cbs[i]) < 0) { perror("aio_read"); return -1; }
                submitted++;
            }
        }
    }
    return 0;
}

/* --------------------------------------------------------------- iouring */
#ifdef HAVE_IOURING
static int io_uring_setup_sc(unsigned entries, struct io_uring_params *p) {
    return (int)syscall(__NR_io_uring_setup, entries, p);
}
static int io_uring_enter_sc(int fd, unsigned to_submit, unsigned min_complete,
                             unsigned flags) {
    return (int)syscall(__NR_io_uring_enter, fd, to_submit, min_complete, flags,
                        NULL, 0);
}

struct uring {
    int fd;
    unsigned *sq_head, *sq_tail, *sq_mask, *sq_array;
    struct io_uring_sqe *sqes;
    unsigned *cq_head, *cq_tail, *cq_mask;
    struct io_uring_cqe *cqes;
};

static int uring_init(struct uring *r, unsigned entries) {
    struct io_uring_params p; memset(&p, 0, sizeof(p));
    r->fd = io_uring_setup_sc(entries, &p);
    if (r->fd < 0) { perror("io_uring_setup"); return -1; }

    size_t sring_sz = p.sq_off.array + p.sq_entries * sizeof(unsigned);
    size_t cring_sz = p.cq_off.cqes + p.cq_entries * sizeof(struct io_uring_cqe);
    /* single mmap works because IORING_FEAT_SINGLE_MMAP on modern kernels */
    if (p.features & IORING_FEAT_SINGLE_MMAP) {
        if (cring_sz > sring_sz) sring_sz = cring_sz;
        cring_sz = sring_sz;
    }
    void *sq = mmap(0, sring_sz, PROT_READ | PROT_WRITE,
                    MAP_SHARED | MAP_POPULATE, r->fd, IORING_OFF_SQ_RING);
    if (sq == MAP_FAILED) { perror("mmap sq"); return -1; }
    void *cq = sq;
    if (!(p.features & IORING_FEAT_SINGLE_MMAP)) {
        cq = mmap(0, cring_sz, PROT_READ | PROT_WRITE,
                  MAP_SHARED | MAP_POPULATE, r->fd, IORING_OFF_CQ_RING);
        if (cq == MAP_FAILED) { perror("mmap cq"); return -1; }
    }
    r->sqes = mmap(0, p.sq_entries * sizeof(struct io_uring_sqe),
                   PROT_READ | PROT_WRITE, MAP_SHARED | MAP_POPULATE,
                   r->fd, IORING_OFF_SQES);
    if (r->sqes == MAP_FAILED) { perror("mmap sqes"); return -1; }

    r->sq_head  = (unsigned *)((char *)sq + p.sq_off.head);
    r->sq_tail  = (unsigned *)((char *)sq + p.sq_off.tail);
    r->sq_mask  = (unsigned *)((char *)sq + p.sq_off.ring_mask);
    r->sq_array = (unsigned *)((char *)sq + p.sq_off.array);
    r->cq_head  = (unsigned *)((char *)cq + p.cq_off.head);
    r->cq_tail  = (unsigned *)((char *)cq + p.cq_off.tail);
    r->cq_mask  = (unsigned *)((char *)cq + p.cq_off.ring_mask);
    r->cqes     = (struct io_uring_cqe *)((char *)cq + p.cq_off.cqes);
    return 0;
}

static int run_iouring(int fd, Config *c) {
    struct uring r;
    if (uring_init(&r, (unsigned)c->qd) < 0) return -1;

    void **bufs = calloc(c->qd, sizeof(void *));
    double *start = calloc(c->qd, sizeof(double));
    for (int i = 0; i < c->qd; i++)
        if (posix_memalign(&bufs[i], 4096, c->bs)) return -1;

    long submitted = 0, completed = 0;
    int inflight = 0;

    while (completed < c->ios) {
        /* fill SQ up to QD */
        unsigned tail = *r.sq_tail;
        int batch = 0;
        while (inflight < c->qd && submitted < c->ios) {
            unsigned idx = tail & *r.sq_mask;
            struct io_uring_sqe *sqe = &r.sqes[idx];
            memset(sqe, 0, sizeof(*sqe));
            sqe->opcode = IORING_OP_READ;
            sqe->fd = fd;
            sqe->addr = (unsigned long long)(uintptr_t)bufs[idx % c->qd];
            sqe->len = c->bs;
            sqe->off = rand_offset(c->bs);
            sqe->user_data = idx % c->qd;
            start[idx % c->qd] = now_ns();
            r.sq_array[idx & *r.sq_mask] = idx & *r.sq_mask;
            tail++; batch++; submitted++; inflight++;
        }
        if (batch) {
            __atomic_store_n(r.sq_tail, tail, __ATOMIC_RELEASE);
        }
        int ret = io_uring_enter_sc(r.fd, batch, 1, IORING_ENTER_GETEVENTS);
        if (ret < 0) { perror("io_uring_enter"); return -1; }

        /* reap completions */
        unsigned chead = *r.cq_head;
        unsigned ctail = __atomic_load_n(r.cq_tail, __ATOMIC_ACQUIRE);
        while (chead != ctail) {
            struct io_uring_cqe *cqe = &r.cqes[chead & *r.cq_mask];
            unsigned slot = (unsigned)cqe->user_data;
            if (cqe->res < 0) { fprintf(stderr, "cqe err %d\n", cqe->res); }
            c->lat_us[c->nlat++] = (now_ns() - start[slot]) / 1e3;
            completed++; inflight--;
            chead++;
        }
        __atomic_store_n(r.cq_head, chead, __ATOMIC_RELEASE);
    }
    return 0;
}
#endif /* HAVE_IOURING */

/* ------------------------------------------------------------------ main */
int main(int argc, char **argv) {
    const char *file = NULL, *engine = "sync";
    long ios = 100000;
    int bs = 4096, qd = 32, threads = 0, direct = 0;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--file") && i + 1 < argc) file = argv[++i];
        else if (!strcmp(argv[i], "--engine") && i + 1 < argc) engine = argv[++i];
        else if (!strcmp(argv[i], "--ios") && i + 1 < argc) ios = atol(argv[++i]);
        else if (!strcmp(argv[i], "--bs") && i + 1 < argc) bs = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--qd") && i + 1 < argc) qd = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--threads") && i + 1 < argc) threads = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--direct")) direct = 1;
        else { fprintf(stderr, "unknown arg %s\n", argv[i]); return 2; }
    }
    if (!file) { fprintf(stderr, "usage: %s --file F [--engine E] [--qd N] [--bs B] [--ios N] [--direct]\n", argv[0]); return 2; }

    int flags = O_RDONLY;
#ifdef O_DIRECT
    if (direct) flags |= O_DIRECT;
#endif
    int fd = open(file, flags);
    if (fd < 0) { perror("open"); return 1; }
    off_t sz = lseek(fd, 0, SEEK_END);
    if (sz < (off_t)bs * 16) { fprintf(stderr, "file too small (%lld bytes)\n", (long long)sz); return 1; }
    file_blocks = sz / bs;
    lseek(fd, 0, SEEK_SET);
    srand(12345);

    Config c = { engine, ios, bs, qd, threads, direct, NULL, 0 };
    c.lat_us = malloc(sizeof(double) * (ios + 1024));
    if (!c.lat_us) { fprintf(stderr, "oom\n"); return 1; }

    double t0 = now_ns();
    int rc = 0;
    if (!strcmp(engine, "sync"))          rc = run_sync(fd, &c);
    else if (!strcmp(engine, "threads"))  rc = run_threads(fd, &c);
    else if (!strcmp(engine, "posixaio")) rc = run_posixaio(fd, &c);
    else if (!strcmp(engine, "iouring")) {
#ifdef HAVE_IOURING
        rc = run_iouring(fd, &c);
#else
        fprintf(stderr, "iouring not supported on this build/platform\n");
        return 3;
#endif
    } else { fprintf(stderr, "unknown engine %s\n", engine); return 2; }
    double wall = (now_ns() - t0) / 1e3;

    if (rc == 0) report(&c, wall);
    close(fd);
    free(c.lat_us);
    return rc;
}
