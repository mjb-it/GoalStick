# **ESP32 Universal LED Controller (NHL Art Piece)**

This firmware transforms the ESP32 into a dedicated serial-controlled LED driver. It is designed to sit behind a high-level controller (Raspberry Pi Zero 2 W) and execute high-performance, non-blocking animations for 300+ WS2812B LEDs.

## **1\. Physical Interface**

### **Wiring Pinout**

| ESP32 Pin | Label | Connection | Purpose |
| :---- | :---- | :---- | :---- |
| **VIN** | 5V | External 5V (+) | Power input (Shared with Pi/Strip) |
| **GND** | GND | External 5V (-) | **Common Ground** (Required) |
| **GPIO 16** | RX2 | Data Resistor | Data Signal to LED Strip |
| **GPIO 16** | RX2 | Pi TX (GPIO 14\) | Serial Command Input |

Export to Sheets

### **Hardware Protection**

* **1000µF Capacitor:** Must be placed across the 5V/GND rails near the power input.  
* **470Ω Resistor:** Must be placed in-line between GPIO 16 and the LED `Data In` pad.  
* **Logic Level Shifter:** Recommended (74AHCT125) to boost 3.3V logic to 5V for reliable signal over long distances.

## **2\. Serial Protocol Specification**

The ESP32 listens on **Hardware Serial 2** (mapped to GPIO 16\) with the following configuration:

* **Baud Rate:** `115200`  
* **Data Bits:** `8`  
* **Parity:** `None`  
* **Stop Bits:** `1`

### **Command Set**

| Command | Format | Description |
| :---- | :---- | :---- |
| **Celebration** | `C:RRGGBB,RRGGBB...` | Triggers the goal animation using the provided hex colors. |
| **Idle** | `I` | Stops any current animation and clears the strip. |

Export to Sheets

#### **Command Example: Washington Capitals**

To trigger a celebration for the Capitals, the Pi sends: `C:FFFFFF,002D62,E51937\n`

* **Prefix:** `C:` tells the ESP32 a color array follows.  
* **Values:** Up to 5 Hexadecimal strings (6 characters, no `#`), comma-separated.  
* **Terminator:** Line feed (`\n`) or carriage return is required to process.

## **3\. Logic & Behavior**

### **Goal Celebration Sequence**

When a valid `C:` command is received:

1. **Impact Phase:** The entire strip flashes the first color of the array 3 times (400ms intervals).  
2. **Chase Phase:** A repeating pattern is generated. Every 10 LEDs represent one color from the array. This pattern "chases" forward at \~50 FPS.  
3. **Timeout:** The animation automatically terminates and clears the strip after **10 seconds**.

### **Multi-Tasking (Non-Blocking)**

The ESP32 uses a `millis()`\-based state machine. This allows the device to:

* Maintain fluid 60Hz animations.  
* Instantly receive an `I` (Idle) command to cancel a celebration (useful for overturned goals).  
* Switch teams mid-animation if a new `C:` command arrives.

## **4\. Troubleshooting**

* **No Response:** Verify the Raspberry Pi and ESP32 share a **Common Ground**.  
* **Flickering LEDs:** Ensure the 5V power supply has enough amperage (min 2A for breadboard testing).  
* **Garbage Serial Output:** Ensure the Baud Rate on the Pi matches exactly `115200`.  
* **Wrong Colors:** If Red and Green are swapped, change the LED type in the firmware from `NEO_GRB` to `NEO_RGB`.

