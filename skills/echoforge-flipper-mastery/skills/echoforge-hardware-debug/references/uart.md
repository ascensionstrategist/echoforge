# UART — Baud Detection, TX/RX Identification, and Console Access

UART (Universal Asynchronous Receiver-Transmitter) is the single most useful debug interface on consumer electronics — most embedded Linux devices and many bare-metal firmwares print a boot log to a UART TX line that's easy to probe. If you can find the TX line, you can read the log; if you can also identify the RX line, you usually get a root shell.

---

## Physical layer

- **TX** (Transmit): output from the device — always driving, idles **high**.
- **RX** (Receive): input to the device — floats or weakly pulled up.
- **GND**: reference ground.
- Optional **VCC** (3.3V or 5V): power for external adapters. Usually not wired on a debug header.
- Optional **CTS / RTS**: hardware flow control. Rare on embedded debug.

**Voltage levels.** Modern embedded UART is **3.3V TTL** (0 = low, 3.3 = high). Older is **5V TTL** (ATmega328 class). PC RS-232 is `±12V` inverted — totally incompatible; never plug a RS-232 DB9 directly into an embedded UART unless you have a MAX3232 level-shifter.

Tools: a USB-to-TTL adapter (CH340, FT232RL, CP2102 — all ~$3). Most are 3.3V + 5V selectable via jumper; default to 3.3V for modern targets.

---

## Identifying TX vs RX on unlabeled pads

You have 2-5 unlabeled pads and need to find UART. Procedure:

1. **Power the board.** Listen/look for boot activity.
2. **Probe each pad with a scope (or Saleae clone) relative to GND.** Look for:
   - A pad that swings 0 ↔ 3.3V rapidly (packets of activity ≤ 10 ms long) during the first few seconds → **that's TX**. It's outputting boot logs.
   - Other pads: likely RX (floating around 3.3V via pull-up) or GPIO.
3. **Cross-check TX.** Even without a scope, a multimeter on DC will show TX briefly wobbling below the rail during traffic; a static 3.3V pad is idle-high (could be RX).
4. **RX identification.** RX is harder — it's quiet from the board side. Once you have TX + GND, try:
   - Short each candidate to GND briefly (only after verifying it's not VCC). If the CPU halts or resets, it's not RX.
   - Connect a USB-TTL adapter's TX to a candidate pad, open `screen` or similar at the known baud, type during boot prompt window — if the boot process pauses or echoes, that pad is RX.

**Hard mode.** 4-pad headers are almost always {VCC, TX, RX, GND}. Eight-pad headers with 2 unknowns mixed in are usually {VCC, TX, RX, GND, BOOT, RESET, NC, NC}.

---

## Detecting baud rate

The most common baud rates on embedded UART, in rough order of frequency:
- **115200** — default on Linux-class SoCs (Broadcom, Qualcomm, Allwinner), U-Boot, OpenWRT.
- **9600** — old defaults, Arduino-style.
- **57600** — some SBCs.
- **38400** — rare but present.
- **19200, 4800, 2400, 1200, 300** — very old.
- **921600, 460800, 230400** — high-speed newer SoCs.

**Trial-and-error method.** Connect TX to your adapter RX. Open `screen /dev/ttyUSB0 115200`. If you see gibberish, try the next. Human-readable output → right baud. Takes about 30 seconds to try all common values by hand.

**Automatic method.** Sigrok / PulseView with the `uart` decoder, or `baudrate.py` (https://github.com/devttys0/baudrate) which scores each baud by how many printable ASCII characters come out.

**Scope-based method.** Measure the shortest pulse width on TX during active traffic. Baud = `1 / pulse_width`. A 8.68 µs pulse = 115200 bps (since 1 / 115200 = 8.68 µs). This only gives you a lower bound (a '1' bit is one pulse, but two adjacent '1' bits look like one longer pulse).

### Standard framing

Default is **8N1**: 8 data bits, No parity, 1 stop bit. 7E1 / 7O1 / 8E1 / 8O1 / 8N2 variants exist but are rare on modern embedded.

Line format:
```
[Start 0][D0][D1][D2][D3][D4][D5][D6][D7][Stop 1]
```

Bits are sent LSB first. A `'A'` (0x41 = 01000001 binary) is wire-transmitted as `0, 1, 0, 0, 0, 0, 0, 1, 0, 1` (start + LSB-first data + stop).

---

## Once you have console access

Boot output of a typical embedded Linux device:

```
U-Boot SPL 2018.03 (Mar 15 2020 - 12:34:56)
DRAM: 256 MiB
Trying to boot from MMC
U-Boot 2018.03 (Mar 15 2020 - 12:34:56)
CPU: Allwinner H3
Model: NanoPi M1
Hit any key to stop autoboot: 2
```

**"Hit any key to stop autoboot"** — this is the golden moment. If you have RX wired and hit any key in time, you drop to the U-Boot prompt with full hardware control:

```
=> help
=> printenv                # view env vars, often including root password hashes
=> md 0x40000000           # dump memory
=> mmc read 0x40000000 0 0x100  # read SD card into RAM
=> bootargs init=/bin/sh   # override init to spawn a shell with no login
=> boot
```

Some vendors have disabled autoboot stop ("silent console" via `CONFIG_SILENT_CONSOLE`). You'll still see boot messages but can't interrupt. Workaround: glitch the U-Boot load (short SPI MISO briefly during flash read to corrupt the boot image, dropping to the BROM U-Boot recovery prompt).

Once Linux boots, you often get a root shell at the login prompt (especially on consumer IoT — many ship with empty `root` password or hardcoded creds you can grep out of the filesystem later).

---

## Flipper as a UART adapter

Flipper's GPIO pins 13 and 14 are mapped to USART1 TX/RX by default. With a FAP like `kid-a-/flipperzero-uart-nmea` or the built-in `GPIO → USB UART Bridge`, Flipper acts as a USB-to-TTL adapter for the target — connect Flipper's pin 13 (TX) to target RX, Flipper's 14 (RX) to target TX, GND to GND, then on your PC `screen /dev/ttyACM0 115200`.

This is handy when you're away from your lab and just need to dump a boot log. Max reliable baud ~460800 in practice.

### Voltage considerations

Flipper's GPIO is **3.3V only**. Driving it with 5V-level UART risks damage — use a level shifter if the target is 5V TTL. RS-232-level serial (±12V) needs a MAX3232 or CP2102 adapter, not raw Flipper GPIO.

---

## Software tools

- **`screen /dev/ttyUSB0 115200`** (Linux/macOS) — simplest. Exit: `Ctrl-A k y`.
- **`minicom`** — interactive, supports logging and file transfer. Ctrl-A for menu.
- **`picocom`** — lightweight screen alternative.
- **`cu -l /dev/ttyUSB0 -s 115200`** — BSD-style.
- **PuTTY** / **Tera Term** (Windows) — GUI serial terminal.
- **`stty -F /dev/ttyUSB0 raw 115200`** + `cat /dev/ttyUSB0` — one-shot raw dump, no terminal emulation.

---

## Common mistakes

1. **TX-to-TX cross-wired.** Both sides driving the same line → contention, gibberish. Remember to cross: TX → RX, RX → TX.
2. **Forgetting GND.** A UART without common ground is a random-voltage generator. GND first, always.
3. **Wrong baud with "mostly readable" output.** Close-but-wrong baud (say 9600 when target is 19200) produces partial readability where some characters correct and others garbage — deceptive. If 50% looks right but 50% is wrong, you're off.
4. **Half-duplex adapters.** Some "USB-TTL" adapters are half-duplex by default (TX and RX muxed). Use a real full-duplex adapter.
