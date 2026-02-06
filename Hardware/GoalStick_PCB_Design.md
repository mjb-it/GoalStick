# GoalStick PCB Design

Carrier board for Pi Zero 2W + ESP32 DevKit to mount on hockey stick.

## Components

| Component | Footprint | Notes |
|-----------|-----------|-------|
| Pi Zero 2W | 2x20 pin header (2.54mm) | 65mm × 30mm |
| ESP32 DevKit V1 | 2x15 pin header (2.54mm) | ~51mm × 28mm |
| Tactile Button | 6mm × 6mm through-hole | Pairing/Reset |
| JST-XH 3-pin | 2.5mm pitch | LED strip connector (5V, GND, Data) |
| 10kΩ Resistor | 0805 SMD or through-hole | Button pull-up (optional, Pi has internal) |

## Schematic

```
                    Pi Zero 2W                          ESP32 DevKit V1
                 ┌──────────────┐                    ┌──────────────────┐
                 │              │                    │                  │
    5V Power ────┤ 5V      3.3V ├                    │ VIN          3V3 │
                 │              │                    │                  │
         GND ────┤ GND      GND ├────────────────────┤ GND          GND ├──── GND
                 │              │                    │                  │
                 │ GPIO14 (TX) ─┼────────────────────┤► GPIO16 (RX2)    │
                 │              │                    │                  │
                 │ GPIO15 (RX) ◄┼────────────────────┼─ GPIO17 (TX2)    │
                 │              │                    │                  │
                 │ GPIO27 ──────┼────────────────────┤► EN (Reset)      │
                 │              │                    │                  │
                 │ GPIO17 ◄─────┼── Button ── GND    │ GPIO4 ───────────┼──── LED Data
                 │              │                    │                  │
                 └──────────────┘                    └──────────────────┘

    LED Strip Connector (JST-XH 3-pin):
    ┌─────┐
    │ 5V  │──── From Pi 5V or external PSU
    │ GND │──── Common ground
    │ DIN │──── From ESP32 GPIO4
    └─────┘
```

## PCB Layout Suggestions

### Board Dimensions
- **Width**: ~80mm (fits hockey stick blade)
- **Height**: ~100mm (stacked vertically: Pi on top, ESP32 below)
- **Mounting holes**: 4x M3 (3.2mm) at corners

### Layout (Top View)
```
    ┌────────────────────────────────────┐
    │  ○                              ○  │  ← Mounting holes
    │                                    │
    │    ┌──────────────────────────┐    │
    │    │     Pi Zero 2W           │    │
    │    │     (header socket)      │    │
    │    └──────────────────────────┘    │
    │                                    │
    │    ┌──────────────────────────┐    │
    │    │     ESP32 DevKit         │    │
    │    │     (header socket)      │    │
    │    └──────────────────────────┘    │
    │                                    │
    │   [BTN]              [JST LED]     │
    │                                    │
    │  ○                              ○  │
    └────────────────────────────────────┘
```

## EasyEDA Steps

1. **Create New Project**: File → New → Project
2. **Create Schematic**: Add components from library
   - Search "2x20 female header 2.54mm" for Pi socket
   - Search "2x15 female header 2.54mm" for ESP32 socket  
   - Search "tactile switch 6mm"
   - Search "JST-XH 3P"
3. **Wire connections** per schematic above
4. **Convert to PCB**: Design → Convert to PCB
5. **Arrange components** and route traces
6. **Order**: Fabrication → JLCPCB

## Power Considerations

- Pi Zero 2W draws ~200-400mA
- ESP32 draws ~80-240mA
- WS2812B LEDs: ~60mA per LED at full white
- **For short strips (<30 LEDs)**: Power from Pi 5V is fine
- **For longer strips**: Use external 5V PSU, share GND only

## Bill of Materials

| Qty | Part | Example Part Number | Est. Cost |
|-----|------|---------------------|-----------|
| 1 | 2x20 Female Header 2.54mm | - | $1 |
| 2 | 1x15 Female Header 2.54mm | - | $1 |
| 1 | 6mm Tactile Switch | - | $0.10 |
| 1 | JST-XH 3-pin Right Angle | B3B-XH-A | $0.20 |
| 4 | M3 Standoffs + Screws | - | $1 |
| 1 | PCB (JLCPCB 5pcs) | - | $5 |

**Total: ~$8-10** (plus shipping)
