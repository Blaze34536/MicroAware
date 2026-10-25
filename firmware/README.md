# Storm Shield firmware

Three classic ESP32 dev boards talking over ESP-NOW broadcast (Wi-Fi channel 1 by default).

| Sketch | Role | What it does |
|---|---|---|
| `habitat_tx/` | `habitat` (A) | Serial frames in, ESP-NOW broadcast out. Also runs loss-calibration bursts. |
| `earth_rx/` | `earth` (B) | Every ESP-NOW frame received becomes one serial frame with RSSI and a timestamp. |
| `sun/` | `sun` (C) | Interferer: bursts of 250-byte junk broadcasts, duty cycle set by a knob. |

## Wiring

Only the Sun needs extra parts: a potentiometer (any value from 10k to 100k) with its outer legs on **3V3** and **GND** and its wiper on **GPIO34**.

## Flashing

arduino-cli is installed at `/home/nihal/code/geauxhack/.venv/tools/arduino-cli`, with the `esp32:esp32` core. From the repo root:

```sh
.venv/tools/arduino-cli compile --upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32 firmware/habitat_tx
.venv/tools/arduino-cli compile --upload -p /dev/ttyUSB1 --fqbn esp32:esp32:esp32 firmware/earth_rx
.venv/tools/arduino-cli compile --upload -p /dev/ttyUSB2 --fqbn esp32:esp32:esp32 firmware/sun
```

To use another channel, add `--build-property "compiler.cpp.extra_flags=-DCHANNEL=6"` and flash **all three** boards with the same value. For the Sun's TX power, use `-DTX_POWER_QDBM=40` (units of 0.25 dBm; the default is 8, which is 2 dBm).

On the laptop, `microaware.link.serial_frame.find_ports()` resets each board and maps the role to the port.

## Serial protocol (921600 baud)

Every binary frame is `0xA5, len, payload[len], crc8`. `len` is 1..250. The CRC is CRC-8 (poly 0x07, init 0x00) over `len` + payload. At boot each board prints one text line, `ROLE <name>`. Lines that start with `#` are debug output. The decoder skips any text it finds between frames.

| Direction | Board | Payload | Meaning |
|---|---|---|---|
| laptop to board | habitat | any bytes (first byte not `0xC0`) | broadcast as is |
| laptop to board | habitat | `0xC0, u16 count, u16 gap_ms, u8 size` | send `count` test frames of `size` bytes: `0x7E, u16 seq, filler` |
| board to laptop | habitat | `0xC1, u16 sent` | test burst finished |
| board to laptop | earth | `i8 rssi, u32 millis, data...` | one received ESP-NOW frame |
| laptop to board | sun | `0xF1, u8 duty%, u16 seconds` | override the knob for `seconds` (0 cancels) |

All multi-byte integers are little-endian. Earth can forward at most 245 bytes of data per frame (250 minus its 5-byte header) and truncates anything longer, so keep the habitat payloads at 245 bytes or less.

## Sun safety

The Sun transmits only while a serial override is active, or while the knob is above 5% **and** was moved within the last 30 s. It shuts itself off 30 s after the last command or knob movement. Each burst cycle has a random length, uniform from 200 to 400 ms, so the Sun never phase-locks with the interleaver. Within a cycle, the Sun transmits for duty × cycle length and then stays quiet.

## Placement (hidden-node setup)

Put the **Sun right beside Earth**. Keep **Habitat a few meters away**, or put it in a foil-lined box, so it can't hear the Sun. ESP-NOW broadcast has no carrier-sense backoff against a node it can't hear and no ACKs or retries, so the collisions happen at Earth, which is what we want to show.
