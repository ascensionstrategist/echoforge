# I2C and SPI Bus Sniffing (stub)

This is a stub reference. Expand as needed.

## I2C

- 2-wire (SDA + SCL + GND), open-drain with pull-ups to VCC.
- 7-bit address space (standard) or 10-bit (extended). `i2cdetect -y 1` on a Pi or `Bus Pirate` `(1)` scan enumerates responders.
- Common devices:
  - **24Cxx / AT24Cxx EEPROM** — configuration storage. Addresses `0x50-0x57`.
  - **PCF8574** — GPIO expander. `0x20-0x27`.
  - **DS3231 RTC** — `0x68`.
  - **MPU6050 IMU** — `0x68`.
- Flipper FAPs: `GPIO → I2C Scanner`, `GPIO → I2C Sniffer`.
- Signal level: 3.3V or 5V TTL depending on board design; Flipper is 3.3V.

## SPI

- 4-wire (SCK + MOSI + MISO + CS), separate CS per slave on a shared bus.
- Modes 0-3 differentiate by clock polarity (CPOL) and phase (CPHA). Mode 0 (CPOL=0, CPHA=0) is the overwhelming default.
- Speeds: 100 kHz – 100 MHz.
- **SPI flash (NOR)** — 8-pin SOIC package, `25xx` part family:
  - `W25Q80` (Winbond, 1 MB), `W25Q16` (2 MB), `W25Q32` (4 MB), `W25Q64` (8 MB), `W25Q128` (16 MB)
  - `MX25L`, `GD25Q`, `SST25VF` — compatible families.
  - Common instruction set: `READ 0x03`, `FAST_READ 0x0B`, `WRITE_ENABLE 0x06`, `PAGE_PROGRAM 0x02`, `SECTOR_ERASE 0x20`, `CHIP_ERASE 0xC7`, `READ_SFDP 0x5A`.
- **Dumping SPI flash:**
  - **In-circuit**: SOP8 test clip + CH341A programmer + `flashrom -p ch341a_spi -r dump.bin`. Risk: power contention with the host SoC; some boards need the SoC held in reset or desoldered.
  - **Out-of-circuit**: desolder the chip, put it in a DIP8 adapter, read standalone. Safer, more annoying.
- Flipper FAPs: `SPI Mem Manager` for in-circuit reads at bit-banged kHz speeds — too slow for full flash dumps (a 16 MB chip at 100 kHz takes ~20 minutes), but fine for spot-reads.

## Tools

- **Bus Pirate** — veteran multi-protocol prober, supports I2C/SPI/UART/JTAG/1-Wire. Slow but universal.
- **Saleae Logic / Kingst LA2016** — USB logic analyzer with Saleae software + `sigrok` drivers.
- **flashrom** — gold-standard SPI flash dumping.
- **CH341A programmer** — $5 USB programmer, SPI/I2C/UART. Comes with SOP8 clip.
