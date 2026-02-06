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

## KiCad Project

Project files are in `Hardware/KiCad/GoalStick.kicad_pro`

### Opening the Project
1. Open KiCad (in Applications)
2. File → Open Project → select `GoalStick.kicad_pro`

### Adding Components to Schematic
Open the schematic editor and add these symbols:

| Symbol | Library | Notes |
|--------|---------|-------|
| Conn_02x20_Odd_Even | Connector_Generic | Pi Zero header |
| Conn_01x15 (x2) | Connector_Generic | ESP32 headers |
| SW_Push | Switch | Tactile button |
| Conn_01x03 | Connector_Generic | LED strip JST |

### Wiring in Schematic
1. Place components
2. Use 'W' key to wire
3. Add power symbols: VCC, +5V, GND
4. Add net labels for clarity (UART_TX, UART_RX, etc.)

### Assigning Footprints
1. Tools → Assign Footprints
2. Suggested footprints:
   - Pi header: `Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical`
   - ESP32 headers: `Connector_PinSocket_2.54mm:PinSocket_1x15_P2.54mm_Vertical`
   - Button: `Button_Switch_THT:SW_PUSH_6mm`
   - JST: `Connector_JST:JST_XH_B3B-XH-A_1x03_P2.50mm_Vertical`

### Creating PCB
1. Tools → Update PCB from Schematic
2. Arrange components
3. Draw board outline on Edge.Cuts layer
4. Route traces (or use autorouter)
5. Run DRC (Inspect → Design Rules Checker)

### Ordering from JLCPCB
1. File → Fabrication Outputs → Gerbers
2. Upload ZIP to jlcpcb.com
3. Default settings work (~$5 for 5 boards)

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
