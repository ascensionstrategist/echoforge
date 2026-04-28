---
name: echoforge-hardware-debug
description: Identify, probe, and reason about hardware debug interfaces (JTAG, SWD, UART, I2C, SPI) exposed on PCBs — what pins do, how to discover chains, how to identify baud rates, and how Flipper Zero's GPIO maps onto each. Educational reference for authorized hardware-security research and firmware dumping.
---

# Hardware Debug Interfaces

You are the expert reference for debug interfaces commonly found on consumer/IoT/embedded PCBs: **JTAG**, **SWD**, **UART**, **I2C**, **SPI**. Understanding these is the difference between "unknown black-box device" and "I can dump the firmware and read it". This is a reference for authorized hardware-security research — your own devices, a client's device under a signed engagement, CTF challenges, or junk-yard recycling.

## When to activate

Load this skill when the user:
- Asks about debug headers / test points on a PCB.
- Shows pinouts or says "I have 4 unlabeled pads, how do I identify them?"
- Asks about JTAG / SWD chain enumeration, boundary scan, or "how do I find JTAG pins?"
- Asks about UART baud-rate detection, `screen /dev/ttyUSB0`, or USB-TTL adapters.
- Asks about SPI flash dumping (W25Q80, MX25L, etc.) or I2C EEPROM reads.
- Uses Flipper's GPIO header for hardware interaction (via Flipper's built-in GPIO app or a JTAG/UART FAP).
- Mentions tools: `JTAGulator`, `Bus Pirate`, `OpenOCD`, `pyOCD`, `flashrom`, `sigrok`, `PulseView`, `Saleae Logic`.

## Core knowledge

**The five debug interfaces you will actually encounter.**

| Interface | Pins | Speed | Primary use | Identify by |
|-----------|------|-------|-------------|-------------|
| **JTAG** | 4 (TCK, TMS, TDI, TDO) + optional TRST | 1-30 MHz | Boundary scan, CPU debug, flash | 4+ unlabeled pads, often with decoupling cap nearby |
| **SWD** | 2 (SWDIO, SWCLK) + GND + optional SWO | 1-25 MHz | ARM Cortex debug (M0/M3/M4/M33, A-series) | Exactly 2 unlabeled data pads next to a reset line |
| **UART** | 2 (TX, RX) + GND + optional VCC | 300 bps – 4 Mbps | Console logs, bootloader prompts | Continuous output when powering on |
| **SPI** | 4 (SCK, MOSI, MISO, CS) | 1-100 MHz | Flash memory, sensors | 8-pin SOIC chip with "25xx" part number |
| **I2C** | 2 (SDA, SCL) + GND + pull-ups | 100 kHz – 3.4 MHz | EEPROMs, configuration chips | Pull-up resistors to VCC, multi-drop |

**The workflow for an unknown PCB.**

1. **Power and clock analysis.** Power the board. Identify VCC and GND rails with a multimeter (continuity to the barrel jack / battery contact). Identify the main SoC and Flash chip by part number.
2. **Visual scan for headers and test points.** Look for:
   - Unpopulated 4/6/10/20-pin headers — common JTAG pitches.
   - Rows of 2-5 unconnected vias near the MCU.
   - TP## silkscreen labels.
3. **UART first.** Probe every unlabeled pad with an oscilloscope or Saleae clone while the board boots. You're looking for a line that carries a burst of ~3.3V digital traffic during the first few seconds. That's UART TX → capture and identify baud.
4. **JTAG/SWD next.** After UART, if you have 4+ remaining unlabeled pads, try JTAG chain discovery (see `references/jtag-swd.md`).
5. **SPI flash if desync'd.** If the main chip is locked but the flash is separate (8-pin SOIC), clip a SOP8 clip onto the flash and dump with `flashrom` or a CH341A programmer. Many vendors ship devices with the CPU's flash readout locked but the SPI NOR flash fully readable.

**Flipper-specific integration.** Flipper's GPIO header (18 pins on top) exposes UART2 (pins 13/14 = TX/RX), SPI1 (pins 2/3/4/5), I2C1 (pins 15/16), plus 14 general-purpose pins. The SWD port (for re-flashing Flipper firmware itself) is on the back 5-pin header; it's for programming Flipper, not targets. Use Flipper with a FAP like `GPIO/Pinout/UART bridge` to talk to a target UART; many third-party FAPs also support SPI sniffing and limited JTAG probing (bit-bang speeds up to ~100 kHz — too slow for real OpenOCD debugging but fast enough for boundary-scan ID reads). See `references/flipper-gpio-pinout.md`.

**Legal context.** Hardware debug on your own devices = fine. Hardware debug on a target's device under a signed penetration-testing ROE = fine. Hardware debug on a device you bought second-hand = generally fine (DMCA § 1201(f) has a reverse-engineering exception, but consult counsel if the product has anti-circumvention). Hardware debug on a device you didn't legitimately obtain = theft + CFAA + whatever other laws apply. Flipper GPIO doesn't know or care, but your ROE should explicitly state "target hardware X, Y, Z debug interfaces authorized".

## Deep references

- **JTAG and SWD** — full protocol reference, chain discovery via JTAGulator / OpenOCD, standard headers (10/20-pin ARM, Xilinx, Altera, PLCC), boundary scan basics, BSDL files, `pyocd list` workflow → `references/jtag-swd.md`
- **UART baud-rate detection** — baud auto-detection by signal analysis, TX vs RX identification, 3.3V vs 5V level issues, common pinouts, `screen`/`minicom`/`picocom` examples, U-Boot/Bootloader interaction → `references/uart.md`
- **I2C and SPI bus sniffing** — Bus Pirate / Saleae setup, address-scan for I2C, SPI flash dump with flashrom, common 24xx/25xx part numbers (stub) → `references/i2c-spi.md`
- **Flipper GPIO pinout** — full 18-pin header mapping, voltage tolerance, pin-mux possibilities, FAP recommendations for each interface (stub) → `references/flipper-gpio-pinout.md`

## Don't confuse with

- **USB** vs **UART** — USB is bus-powered, packet-switched, high-speed (1.5–480 Mbps–5 Gbps). UART is point-to-point, async, 3.3V or 5V TTL, slow. You cannot plug a UART TX into a USB data pin and expect it to work; you need a USB-TTL adapter (CH340, FT232, CP2102).
- **JTAG** vs **SWD** — JTAG is 4-pin, multi-drop (one bus, many devices in a chain). SWD is 2-pin, single-target, ARM-only. An ARM Cortex-M chip often exposes both; you'd pick SWD because it's 2 pins instead of 4.
- **I2C** vs **SMBus** — SMBus is a strict subset of I2C with additional timing requirements (25 ms timeout, 10 kHz minimum clock). Most I2C tools work with SMBus devices; the reverse is not always true.
- **SPI** vs **QSPI / Octal SPI** — QSPI uses 4 data lines, Octal SPI uses 8, for higher throughput on flash. Same electrical family but the sniffing setup and flashrom mode differ.
- **HID over USB** (DuckyScript, BadUSB) vs **debug over USB (DFU, DfuSe)** — DfuSe is a USB-based firmware update protocol; not a debug interface, but sometimes confused with one. DFU is a one-shot flash-write mode.
- **In-System Programming (ISP)** on Atmel AVRs — looks like SPI (MISO/MOSI/SCK/RESET) but uses AVR-specific commands. Tools: `avrdude` + USBasp. Not generic SPI.
