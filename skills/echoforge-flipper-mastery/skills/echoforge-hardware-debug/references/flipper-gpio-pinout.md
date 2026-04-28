# Flipper Zero GPIO Pinout (stub)

This is a stub reference. Expand as needed.

## Top header (18 pins)

```
 1 +5V      2 SPI1 SCK (PA5)
 3 SPI1 MOSI (PA7)   4 SPI1 MISO (PA6)
 5 SPI1 CS (PA4)     6 SWCLK (PA14)        # Flipper's own SWD, for reflashing
 7 GND               8 SWDIO (PA13)        # do not use as general GPIO
 9 +3.3V            10 PA0 (GP / CC1101)
11 PC3 (GP)         12 PC1 (GP)
13 USART1 TX (PB6)  14 USART1 RX (PB7)
15 I2C1 SCL (PB8)   16 I2C1 SDA (PB9)
17 PC0 (GP)         18 GND
```

## Key facts

- **Voltage:** All GPIO is 3.3V. Not 5V-tolerant on most pins. Driving a 5V signal into GPIO risks damage.
- **Current:** ~8 mA per pin sink/source, ~50 mA total for the header.
- **+5V pin (1):** USB-sourced, only available when Flipper is plugged into USB.
- **+3.3V pin (9):** from Flipper's own 3.3V rail; ~100 mA available for powering external sensors.
- **SWD pins (6, 8):** these are Flipper's SWD interface — used for reflashing Flipper firmware itself, NOT for driving external SWD. Don't connect these to a target's SWD.

## Useful FAPs

| FAP | Purpose | Repo |
|-----|---------|------|
| `GPIO / USB-UART Bridge` | UART bridge (stock) | built-in |
| `GPIO / Pinout` | show pin map on-screen | built-in |
| `SPI Mem Manager` | SPI flash dump | 3rd-party FAP |
| `I2C Scanner` | Scan for I2C devices | 3rd-party FAP |
| `JTAG Scanner` | Bit-bang JTAG discovery | 3rd-party FAP |
| `Logic Analyzer` | Basic 8-ch logic capture | 3rd-party FAP |

See the Flipper Applications catalog at https://lab.flipper.net for current FAPs.

## Common wiring patterns

### UART to target
- Flipper pin 13 (TX) → target RX
- Flipper pin 14 (RX) → target TX
- Flipper pin 18 (GND) → target GND

### I2C to target
- Flipper pin 15 (SCL) → target SCL
- Flipper pin 16 (SDA) → target SDA
- Flipper pin 18 (GND) → target GND
- Target needs its own pull-ups to its VCC (Flipper does not provide)

### SPI flash in-circuit dump
- Flipper pin 2 (SCK) → flash CLK
- Flipper pin 3 (MOSI) → flash DI
- Flipper pin 4 (MISO) → flash DO
- Flipper pin 5 (CS) → flash CS
- GND to GND
- Target SoC held in reset externally (strong recommendation to avoid contention)
