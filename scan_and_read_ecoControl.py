import asyncio
from bleak import BleakScanner, BleakClient

# Define the target names we are looking for (case-insensitive substrings)
TARGET_KEYWORDS = ["tael", "tsense"]

async def read_device_characteristics(device):
    """Connects to a given BLE device and dumps its readable GATT characteristics."""
    print(f"\n🔗 Connecting to {device.name} ({device.address})...")
    try:
        async with BleakClient(device) as client:
            print(f"✅ Connected to {device.name}!")
            
            for service in client.services:
                print(f"\n  [Service] {service.uuid}")
                for char in service.characteristics:
                    print(f"    [Char] {char.uuid} | Properties: {char.properties}")
                    
                    if "read" in char.properties:
                        try:
                            value = await client.read_gatt_char(char.uuid)
                            # Displaying both raw hex, decimal list, and ASCII string decoding if readable
                            ascii_str = ""
                            try:
                                ascii_str = f" | Text: '{value.decode('utf-8').strip()}'"
                            except Exception:
                                pass
                                
                            print(f"      ↳ Raw Hex: {value.hex()} | Int List: {list(value)}{ascii_str}")
                        except Exception as e:
                            print(f"      ↳ ❌ Could not read value: {e}")
    except Exception as e:
        print(f"❌ Failed to connect or interact with {device.address}: {e}")

async def main():
    print("🔎 Scanning for Bluetooth devices (5 seconds)...")
    devices = await BleakScanner.discover(timeout=5.0)
    
    target_devices = []

    # Process discovered devices
    for d in devices:
        if d.name:
            name_lower = d.name.lower()
            # Check if any of our target keywords match the device name
            if any(keyword in name_lower for keyword in TARGET_KEYWORDS):
                print(f"🎯 Found Target Match: '{d.name}' | MAC: {d.address}")
                target_devices.append(d)
            else:
                # Still print other devices with low prominence for awareness
                print(f"   Skipping: '{d.name}' | MAC: {d.address}")

    if not target_devices:
        print(f"\n⚠️ No devices matching {TARGET_KEYWORDS} were found in range.")
        return

    print(f"\n🚀 Found {len(target_devices)} candidate device(s). Starting sequential reading...")
    
    # Process each discovered target device sequentially
    for device in target_devices:
        await read_device_characteristics(device)

if __name__ == "__main__":
    asyncio.run(main())
