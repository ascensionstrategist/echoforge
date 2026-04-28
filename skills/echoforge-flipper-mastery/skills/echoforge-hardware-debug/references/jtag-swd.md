# JTAG and SWD

JTAG (IEEE 1149.1, 1990) was originally a boundary-scan testing protocol for ICs; over time it became the de-facto CPU debugging interface on virtually every embedded platform. SWD (ARM's Serial Wire Debug, 2006) is a 2-pin ARM-specific alternative that carries the same debug payload.

---

## JTAG

### Pins

| Pin | Name | Direction | Purpose |
|-----|------|-----------|---------|
| TCK | Test Clock | In | Clocks the state machine |
| TMS | Test Mode Select | In | State transitions (TAP controller FSM) |
| TDI | Test Data In | In | Serial data into chip |
| TDO | Test Data Out | Out | Serial data out of chip |
| TRST | Test Reset | In (optional) | Async reset of TAP controller |

Standard optional additions: SRST (system reset), VREF (target voltage reference).

### TAP controller state machine (abbreviated)

The 16-state FSM is driven by TMS transitions on each TCK rising edge:
- **Test-Logic-Reset** → idle
- **Run-Test/Idle** → waiting
- **Select-DR-Scan** → into DR path (data register)
- **Capture-DR** → **Shift-DR** (shift bits in via TDI, out via TDO) → **Exit1-DR** → **Pause-DR**/**Update-DR** → back to Idle
- Same pattern for **Select-IR-Scan** → Shift-IR path (instruction register)

5 TCK pulses with TMS high always returns to Test-Logic-Reset from any state. This is the "universal reset" trick used by discovery tools.

### Finding JTAG pins on unknown pads

**JTAGulator** (Joe Grand, https://github.com/grandideastudio/jtagulator) is the canonical tool. Connect up to 24 pins; it cycles through all permutations, looking for a response to IDCODE (the default instruction that returns the device ID). You'll learn:
- Which 4 of your N pins are TCK/TMS/TDI/TDO.
- The IDCODE(s) — one per device in the chain.
- Basic chain structure.

**Flipper as a slow JTAGulator:** Flipper FAPs like `airat80/uart_jtag_sniffer` or `cathedral/flipperzero-jtag-fap` bit-bang JTAG at kHz speeds. Works for 4-pin discovery; too slow to usefully drive `openocd`.

### IDCODE decoding

IDCODE is a 32-bit register; structure per IEEE 1149.1:

```
[version 4][part number 16][manufacturer 11][fixed 1]
```

- **Manufacturer** — JEDEC JEP106 code. Examples: `0x00F` = Broadcom, `0x23B` = ARM, `0x477` = Atmel, `0x19C` = STMicro.
- **Part number** — vendor-assigned.
- **Version** — silicon revision.

A sample IDCODE: `0x4BA00477`. Breaking it down: version `0x4`, part `0xBA00`, mfr `0x23B` (ARM), fixed bit `1`. → ARM Cortex-M debug port.

Lookup tables: https://github.com/szymonh/jtag-idcodes.

### Standard JTAG headers

| Pitch | Pin count | Standard |
|-------|-----------|----------|
| 2.54 mm | 20 | ARM 20-pin (also called "JTAG 2.54mm") |
| 1.27 mm | 20 | ARM Cortex Debug (20-pin 0.05") |
| 1.27 mm | 10 | ARM Cortex Debug (10-pin 0.05") |
| 2.54 mm | 14 | TI MSP430, Xilinx, Altera |
| 2.54 mm | 6 | Compact AVR/Atmel |

The 10-pin ARM Cortex Debug (1.27 mm pitch) is the most common on post-2015 ARM hardware:

```
 1 VTref    2 SWDIO/TMS
 3 GND      4 SWCLK/TCK
 5 GND      6 SWO/TDO
 7 KEY      8 NC/TDI
 9 GND      10 /RESET
```

Pin 1 is VTref (target voltage reference, not power). VCC is typically delivered via a separate header or through the board's normal power.

---

## SWD

### Pins

Just 2 data lines + ground:

| Pin | Name | Purpose |
|-----|------|---------|
| SWDIO | Bidirectional data | Read/write DP + AP registers |
| SWCLK | Clock | 1-25 MHz typical |
| GND | — | — |
| SWO | Serial Wire Output (optional) | Unidirectional trace/ITM output |

### Chip support

SWD is ARM-only. Every ARM Cortex-M (M0/M0+/M3/M4/M7/M23/M33) supports it. Cortex-A also supports it in addition to JTAG. Non-ARM cores (MIPS, RISC-V, Xtensa) do not — they use JTAG or vendor-specific protocols.

### SWD vs JTAG tradeoff

- SWD: 2 fewer pins. Single target only (no chain).
- JTAG: 4 pins + chain support. Universal.

If you're debugging an ARM Cortex-M in isolation → use SWD. If you have a board with multiple ICs sharing a debug header → JTAG chain.

### Discovering SWD

- Tools: `OpenOCD` with adapters like ST-Link, J-Link, CMSIS-DAP. pyOCD is a lighter Python-based driver.
- `openocd -f interface/stlink.cfg -f target/stm32f4x.cfg` — typical invocation. Without a matching target config, try `openocd -f interface/stlink.cfg -c "transport select swd" -c "dap create dap.1 -chain-position target.1" -c "init"` and read `dap info`.
- `pyocd list` shows all connected debug probes; `pyocd commander` opens an interactive session.

Once you have SWD access to a Cortex-M, you have:
- Full memory read/write (if not firewalled).
- CPU halt/step/resume.
- Flash erase/program.
- ITM trace capture for printf-style debug.

### Readout protection

Most modern MCUs implement a **readout protection level** fuse:
- STM32: `RDP Level 0` (open), `Level 1` (flash unreadable via SWD, still debuggable), `Level 2` (SWD permanently disabled).
- NXP: CRP1/2/3.
- Nordic: APPROTECT.

If RDP Level 1 is set, you can still connect but all flash reads return 0x00 (or the tool errors out). Level 2 / CRP3 make SWD entirely unreachable — you'd need glitch-injection (voltage/EM) to bypass, which is out of scope for a Flipper-class setup.

---

## Boundary scan

Every JTAG-capable IC has a **boundary scan register** (BSR) — a shift register of cells, one cell per I/O pin. Loading the `SAMPLE` instruction and shifting out the BSR tells you the live state of every pin at that clock edge. Loading `EXTEST` lets you drive pins.

Uses: pin-level test without probing (classic IC-verification use case), "safe-state" forcing (park all pins in a known state), discovering what's on a bus without a logic analyzer.

**BSDL files** describe the BSR structure per chip. http://bsdl.info hosts thousands. Without a BSDL, you can still count BSR length (shift 1s through and see when they emerge) but not know which cell is which pin.

Most hardware debug from a Flipper-class setup skips boundary scan in favor of CPU-level debug (faster, more useful) — but knowing it's an option helps when CPU debug is fused off.

---

## Common JTAG/SWD pitfalls

1. **Voltage mismatch.** Target is 1.8V, adapter is 3.3V → target I/Os take damage over time (pins clamp through ESD diodes). Check VTref, use a level shifter if your adapter doesn't auto-detect.
2. **VCC from the adapter.** Don't let the JTAG adapter power the target unless you know it can. Most targets power themselves; VTref is ONLY a voltage reference, not power.
3. **TRST accidentally held low.** Some boards tie TRST to the system reset line with a pull-up; if you probe the wrong pad as TRST and drag it low, the CPU reboots continuously.
4. **Chain order confusion.** JTAG chains are ordered. In a 3-chip chain (CPU-FPGA-CPLD), the instruction register is the concatenation of all three IRs; you shift through chip-nearest-to-TDI first.
5. **TCK too fast.** Adapters default to 10-30 MHz; if the target is loosely coupled (long wires, breadboard), try 1 MHz first. Reliability before speed.
