/*
 * j5-isttool: talk to the SM-J530F Imagis IST3038H from TWRP over /dev/i2c-11,
 * with the same register protocol as bsd/dev/j5_touch.c (4-byte big-endian
 * address, repeated START, 4-byte big-endian value). Freestanding aarch64
 * Linux binary, raw syscalls, no libc.
 *
 *   j5-isttool r REG [COUNT [INTERVAL_MS]]   read REG, print changes
 *   j5-isttool w REG VALUE                   write REG = VALUE
 *   j5-isttool p REG                         read S2MPU05 register (i2c-0, 0x66)
 *   j5-isttool P REG VALUE                   write S2MPU05 register
 *
 * Build: clang --target=aarch64-linux-gnu -nostdlib -static -ffreestanding
 *        -fno-stack-protector -O2 j5-isttool.c -o j5-isttool (ld.lld)
 */
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

static long sys(long n, long a, long b, long c, long d)
{
	register long x8 __asm__("x8") = n;
	register long x0 __asm__("x0") = a;
	register long x1 __asm__("x1") = b;
	register long x2 __asm__("x2") = c;
	register long x3 __asm__("x3") = d;
	__asm__ volatile("svc 0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3) : "memory");
	return x0;
}

static void out(const char *s)
{
	long n = 0;
	while (s[n]) n++;
	sys(64, 1, (long)s, n, 0);
}

static void hex(u32 v)
{
	char b[11] = "0x00000000";
	for (int i = 0; i < 8; i++) b[9 - i] = "0123456789abcdef"[(v >> (4 * i)) & 15];
	out(b);
}

static u32 parse(const char *s)
{
	u32 v = 0;
	if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) s += 2;
	for (; *s; s++) {
		char c = *s;
		v = v * 16 + (c >= 'a' ? c - 'a' + 10 : c >= 'A' ? c - 'A' + 10 : c - '0');
	}
	return v;
}

static u32 parse_dec(const char *s)
{
	u32 v = 0;
	for (; *s; s++) v = v * 10 + (u32)(*s - '0');
	return v;
}

struct i2c_msg { u16 addr, flags, len; u8 *buf; };
struct i2c_rdwr { struct i2c_msg *msgs; u32 n; };
#define I2C_RDWR 0x0707
#define SLAVE 0x50

static int fd;

static int ist_read(u32 reg, u32 *val)
{
	u8 a[4] = {reg >> 24, reg >> 16, reg >> 8, reg}, b[4];
	struct i2c_msg m[2] = {{SLAVE, 0, 4, a}, {SLAVE, 1, 4, b}};
	struct i2c_rdwr d = {m, 2};
	if (sys(29, fd, I2C_RDWR, (long)&d, 0) != 2) return -1;
	*val = ((u32)b[0] << 24) | ((u32)b[1] << 16) | ((u32)b[2] << 8) | b[3];
	return 0;
}

static int ist_write(u32 reg, u32 v)
{
	u8 a[8] = {reg >> 24, reg >> 16, reg >> 8, reg, v >> 24, v >> 16, v >> 8, v};
	struct i2c_msg m[1] = {{SLAVE, 0, 8, a}};
	struct i2c_rdwr d = {m, 1};
	return sys(29, fd, I2C_RDWR, (long)&d, 0) == 1 ? 0 : -1;
}

static int pmic(int write, u32 reg, u32 *val)
{
	int pfd = (int)sys(56, -100, (long)"/dev/i2c-0", 2, 0);
	u8 a[2] = {reg, *val}, b[1];
	struct i2c_msg w[1] = {{0x66, 0, 2, a}};
	struct i2c_msg r[2] = {{0x66, 0, 1, a}, {0x66, 1, 1, b}};
	struct i2c_rdwr d = {write ? w : r, write ? 1 : 2};
	long n;
	if (pfd < 0) return -1;
	n = sys(29, pfd, I2C_RDWR, (long)&d, 0);
	sys(57, pfd, 0, 0, 0);
	if (n != (long)d.n) return -1;
	if (!write) *val = b[0];
	return 0;
}

static void sleep_ms(u32 ms)
{
	long ts[2] = {ms / 1000, (long)(ms % 1000) * 1000000};
	sys(101, (long)ts, 0, 0, 0);
}

static int run(int argc, char **argv)
{
	fd = (int)sys(56, -100, (long)"/dev/i2c-11", 2, 0);
	if (fd < 0) { out("open /dev/i2c-11 failed\n"); return 1; }
	if (argc >= 3 && argv[1][0] == 'r') {
		u32 reg = parse(argv[2]), count = argc > 3 ? parse_dec(argv[3]) : 1;
		u32 ms = argc > 4 ? parse_dec(argv[4]) : 20, last = 0xffffffffu, v;
		for (u32 i = 0; i < count; i++) {
			if (ist_read(reg, &v)) { out("read error\n"); }
			else if (v != last || count == 1) { hex(reg); out(" = "); hex(v); out("\n"); last = v; }
			if (i + 1 < count) sleep_ms(ms);
		}
		return 0;
	}
	if (argc >= 4 && argv[1][0] == 'w') {
		int r = ist_write(parse(argv[2]), parse(argv[3]));
		out(r ? "write error\n" : "ok\n");
		return r ? 1 : 0;
	}
	if (argc >= 3 && (argv[1][0] == 'p' || argv[1][0] == 'P')) {
		u32 v = argc > 3 ? parse(argv[3]) : 0;
		if (pmic(argv[1][0] == 'P', parse(argv[2]), &v)) { out("pmic error\n"); return 1; }
		out("pmic "); hex(parse(argv[2])); out(" = "); hex(v); out("\n");
		return 0;
	}
	out("usage: j5-isttool r REG [COUNT [MS]] | w REG VALUE | p REG | P REG VALUE\n");
	return 2;
}

__attribute__((naked, noreturn)) void _start(void)
{
	__asm__ volatile(
	    "ldr x0, [sp]\n"
	    "add x1, sp, #8\n"
	    "bl c_main\n");
}

__attribute__((noreturn, used)) void c_main(long argc, char **argv)
{
	long r = run((int)argc, argv);
	sys(93, r, 0, 0, 0);
	for (;;) {}
}
