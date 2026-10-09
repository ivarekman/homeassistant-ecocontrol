# homeassistant-ecocontrol
A lightweight, read-only Home Assistant custom integration for **Taelek Oy ecoControl** Bluetooth floor heating thermostats. 

## Features

- **Pure Read-Only Architecture:**
- **Hybrid Data Gathering:** 
  - Passive discovery scanning extracts custom given device names and floor temperature from over-the-air manufacturer advertisement payloads.
  - Active GATT connection sync polls additional details.
- **HACS Ready:** Ready to be added as a custom repository immediately.

---

## Technical Overview & Payload Mapping

Through thorough raw byte-level packet tracing, this integration maps parameters straight out of unmanipulated IEEE data structures:

### 1. Passive Discovery Advertisement (Manufacturer ID: `1162` / `0x048A`)
The thermostat packs its identity metadata into a single 18-byte passive burst payload:
```text
c400102d7ddf8c6a416c61203137383736...
```
* **Bytes 0-1 (`c4 00`):** Little-endian Manufacturer ID signature.
* **Bytes 8+ onwards:** Dynamic UTF-8 given device name string block (e.g., extracts `Ylä 17876` or `Ala 178760`).

### 2. High-Resolution Active GATT Registers
When Home Assistant runs its 10-minute coordination interval loop, it securely connects to read structural endpoints directly using standard `struct` integer unpack sequences:

* **Characteristic `2be32db1-5f6b-4cbd-8843-8d6dfb164900` (Details):**
  * **Bytes 0-1:** `error_code` (Unsigned 16-bit Short)
  * **Bytes 6-7:** `air_temp` (Unsigned 16-bit Short / 10.0) -> Yields native high-resolution Celsius.
  * **Bytes 8-9:** `floor_temp` (Unsigned 16-bit Short / 10.0) -> Yields native high-resolution Celsius.
* **Characteristic `2be32db1-5f6b-5bd8-8238-d6dfb1649000` (Setpoint & Serial):**
  * **Bytes 0-1:** `desired_temp` (Target setpoint fallback limits)
  * **Bytes 6-14:** `serial` (ASCII text string container decoding directly to your exact device serial tracking numbers).
* **Characteristic `2be32db1-5f6b-4cbd-8813-8d6dfb164900` (Hardware Profile):**
  * Parses static board configurations, natively extracting the Software Version from the ASCII integer conversion value of the trailing firmware letters (e.g., ASCII `K` maps directly to dynamic **Software version 75**).

---

## Exposed Entities

The integration exposes the following read-only sensor entities into your unified device panels:
* **Air temperature** (°C)
* **Floor temperature** (°C) (passive)
* **Desired temperature** (°C)
* **Error code**
* **Hardware version**
* **Software version**
* **Serial number**

---

## Installation via HACS

1. Ensure **HACS** is installed and operational on your Home Assistant instance.
2. Go to **HACS** -> **Integrations**.
3. Click the **three dots** in the top-right corner and select **Custom repositories**.
4. Paste your GitHub repository URL into the **Repository** field.
5. Select **Integration** from the Category dropdown menu list and click **Add**.
6. Find the **ecoControl Floor Heating** card tile and click **Download**.
7. Restart Home Assistant completely.

## Manual installation

1. Copy files to Home Assistant into a new folder custom_components/ecocontrol/
2. Settings -> Tools -> YAML -> Check Configuration.
3. Settings -> Tools -> YAML -> Restart -> Restart Home Assistant

If valid, click Restart to reboot Home Assistant.

## Configuration

1. In Home Assistant, navigate to **Settings** -> **Devices & Services**.
2. If your device is not automatically discovered click **+ Add Integration** in the bottom right.
3. Search for **ecoControl Floor Heating**.
4. The setup discovery wizard window will list your physical thermostats cleanly by their customized localized given names (e.g., `17876 [MAC]`). Select your device and click Submit.
5. Remember to set the scanning interval using the Configure-button. Default poll interval is 600s (10min).

## ESPHome Bluetooth Proxy 
By default an ESP32 ESPHome Bluetooth Proxy may only perform passive scanning. To read all ecoControl ecoControl values a GATT connection is needed. To make this work, enable active mode your ESPHome configuration.
