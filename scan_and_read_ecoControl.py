import asyncio
import logging
import struct
from typing import Any
from bleak import BleakScanner, BleakClient

# Strict Keyword Boundaries
TARGET_KEYWORDS = ["tael", "tsense"]
ECOCONTROL_MFR_ID = 1162

# Core GATT Characteristics definitions matching your integration
UUID_NAME = "2be32db1-5f6b-4cbd-8833-8d6dfb164900"
UUID_HW = "2be32db1-5f6b-4cbd-8813-8d6dfb164900"
UUID_SERIAL_SETPOINT = "2be32db1-5f6b-5bd8-8238-d6dfb1649000"
UUID_DETAILS = "2be32db1-5f6b-4cbd-8843-8d6dfb164900"

# Consumption Statistics Characteristic verified via raw trace analysis
UUID_STAT_8863 = "2be32db1-5f6b-4cbd-8863-8d6dfb164900"


def clean_bytes_to_string(raw_bytes: bytes) -> str:
    """Safely decodes raw hardware byte buffers into clean strings."""
    try:
        text = raw_bytes.decode("utf-8", errors="ignore").strip()
    except Exception:
        text = "".join(chr(b) for b in raw_bytes if 32 <= b <= 126 or b >= 128).strip()
    text = "".join(c for c in text if c.isprintable()).strip()
    if text.endswith(" 2Z"):
        text = text[:-3].strip()
    return text


def unpack_uint16(payload: bytes, offset: int) -> int | None:
    """Extracts a standard single 16-bit little-endian integer securely."""
    if len(payload) < (offset + 2):
        return None
    val_tuple = struct.unpack_from("<H", payload, offset)
    return int(val_tuple[0])


def unpack_uint32(payload: bytes, offset: int) -> int | None:
    """Extracts a standard single 32-bit little-endian integer securely."""
    if len(payload) < (offset + 4):
        return None
    val_tuple = struct.unpack_from("<I", payload, offset)
    return int(val_tuple[0])


def parse_name_from_mfr(mfr_bytes: bytes) -> str | None:
    """Passively extracts and decodes the string name out of index 8."""
    if len(mfr_bytes) < 9:
        return None
    try:
        name_bytes = mfr_bytes[8:]
        return clean_bytes_to_string(name_bytes)
    except Exception:
        return None


def parse_floor_temp_from_mfr(mfr_bytes: bytes) -> float | None:
    """Passively extracts and decodes the floor temperature out of index 0 safely."""
    if not mfr_bytes or len(mfr_bytes) < 1:
        return None
    try:
        raw_floor = int(mfr_bytes[0])
        return round(float(raw_floor) / 10.0, 1)
    except Exception:
        return None


def parse_thermostat_payload(
    raw_name: bytes,
    raw_hw: bytes,
    raw_serial_block: bytes,
    raw_details: bytes,
    raw_8863: bytes,
    fallback_name: str,
    raw_passive_flags: int = 0
) -> dict[str, Any]:
    """Parses raw GATT binary arrays into a clean state dictionary matching integration requirements."""
    name = clean_bytes_to_string(raw_name) or fallback_name
    
    serial = None
    if len(raw_serial_block) >= 15:
        serial = clean_bytes_to_string(raw_serial_block[6:15])

    hw_version = "4.0T"
    software_version = None
    if len(raw_hw) >= 15 and raw_hw[14] > 0:
        software_version = str(raw_hw[14])
    
    error_code = None
    operation_mode = None
    desired_temp = None
    air_temp = None
    floor_temp = None
    
    # Heating relay state derived bitwise from the passive airwave flag register mask
    is_heating = bool(raw_passive_flags & 0x80)

    if len(raw_details) >= 12:
        error_code = unpack_uint16(raw_details, 0)
        operation_mode = unpack_uint16(raw_details, 2)
        desired_raw = unpack_uint16(raw_details, 4)
        air_raw = unpack_uint16(raw_details, 6)
        floor_raw = unpack_uint16(raw_details, 8)

        if air_raw is not None:
            air_temp = round(air_raw / 10.0, 1)
        if floor_raw is not None:
            floor_temp = round(floor_raw / 10.0, 1)
        if desired_raw is not None:
            desired_temp = round(desired_raw / 10.0, 1)

    # Unpack long-term counter values out of 8863 block
    relay_cycles = unpack_uint32(raw_8863, 0) if len(raw_8863) >= 4 else None
    operating_hours = unpack_uint32(raw_8863, 4) if len(raw_8863) >= 8 else None
    heating_hours_raw = unpack_uint32(raw_8863, 8) if len(raw_8863) >= 12 else None
    heating_hours = round(heating_hours_raw / 100.0, 2) if heating_hours_raw is not None else None

    return {
        "name": name,
        "hw_version": hw_version,
        "software_version": software_version,
        "serial": serial,
        "error_code": error_code,
        "operation_mode": operation_mode,
        "air_temp": air_temp,
        "floor_temp": floor_temp,
        "desired_temp": desired_temp,
        "is_heating": is_heating,
        "relay_cycles": relay_cycles,
        "operating_hours": operating_hours,
        "heating_hours": heating_hours,
    }


async def read_device_active_data(device, passive_data: dict):
    """🚀 STAGE 2: Connects and maps all discovered raw GATT structures side-by-side cleanly."""
    print(f"\n🔗 Attempting Active GATT Connection to {device.address}...")
    try:
        async with BleakClient(device, timeout=10.0) as client:
            print(f"   ✅ Connected! Extracting diagnostic logs...")
            
            raw_name = await client.read_gatt_char(UUID_NAME)
            raw_hw = await client.read_gatt_char(UUID_HW)
            raw_serial_block = await client.read_gatt_char(UUID_SERIAL_SETPOINT)
            raw_details = await client.read_gatt_char(UUID_DETAILS)
            
            # Read consumption characteristics safely
            raw_8863 = b""
            try:
                raw_8863 = await client.read_gatt_char(UUID_STAT_8863)
            except Exception:
                pass

            print(f"\n   🔍 [RAW ACTIVE CHARACTERISTIC TRACE]")
            print(f"      • UUID_DETAILS       ➔ Hex: {raw_details.hex()}")
            if raw_8863:
                print(f"      • UUID_STAT_8863     ➔ Hex: {raw_8863.hex()}")
            
            raw_flags_byte = passive_data.get("raw_flags_byte", 0)
            parsed = parse_thermostat_payload(
                raw_name, raw_hw, raw_serial_block, raw_details, raw_8863,
                device.name or "ecoControl", raw_flags_byte
            )

            print("\n   📦 UNPACKED PARSING RESULTS:")
            print(f"      • Hardware Reg Name  : '{parsed['name']}'")
            print(f"      • Device Serial No   : {parsed['serial']}")
            print(f"      • HW / SW Version    : {parsed['hw_version']} / v{parsed['software_version']}")
            print(f"      • System Error Code  : {parsed['error_code'] if parsed['error_code'] != 0 else '-'}")
            print(f"      • Operational Mode   : {parsed['operation_mode']}")
            print(f"      • Room Air Temp      : {parsed['air_temp']}°C")
            print(f"      • Reg Floor Temp     : {parsed['floor_temp']}°C")
            print(f"      • Target Setpoint    : {parsed['desired_temp']}°C")
            print(f"      • Relay (Heating)    : {parsed['is_heating']}")
            
            if parsed['relay_cycles'] is not None:
                print(f"\n      📊 [HISTORICAL CONSUMPTION LOGS]:")
                print(f"        ├── Relay Cycle Count : {parsed['relay_cycles']} clicks")
                print(f"        ├── Operating Time    : {parsed['operating_hours']} hours")
                print(f"        └── Total Heating Time: {parsed['heating_hours']} hours")
            print("   " + "-" * 60)
            
    except Exception as e:
        print(f"   ❌ [ACTIVE SESSION FAILED]: {e}")


async def main():
    print("🔎 STAGE 1: Passive scanning for airwave advertisement packages (5 seconds)...")
    devices_dict = await BleakScanner.discover(timeout=5.0, return_adv=True)
    
    target_registry = []

    print("\n📋 ================= RAW & DECODED PASSIVE ANALYSIS =================")
    for address, (device, adv) in devices_dict.items():
        name = device.name or adv.local_name or ""
        name_lower = name.lower()
        
        is_target = any(k in name_lower for k in TARGET_KEYWORDS) or (ECOCONTROL_MFR_ID in adv.manufacturer_data)
        if not is_target:
            continue
            
        passive_metrics = {"name": None, "floor_temp": None, "raw_flags_byte": 0}
        print(f"\n🎯 Discovered Node: '{name}' | MAC: {address} | RSSI: {adv.rssi}dBm")
        
        if adv.manufacturer_data and ECOCONTROL_MFR_ID in adv.manufacturer_data:
            payload = adv.manufacturer_data[ECOCONTROL_MFR_ID]
            
            if len(payload) >= 3:
                passive_metrics["raw_flags_byte"] = int(payload[2])
                
            passive_metrics["name"] = parse_name_from_mfr(payload)
            passive_metrics["floor_temp"] = parse_floor_temp_from_mfr(payload)
            
            print("   • Decoded Passive Broadcast Telemetry:")
            print(f"       ↳ Parsed Name       : {passive_metrics['name']}")
            print(f"       ↳ Parsed Floor Temp : {passive_metrics['floor_temp']}°C")
            print(f"       ↳ Raw Flag Register : {hex(passive_metrics['raw_flags_byte'])}")
            
        target_registry.append((device, passive_metrics))

    print("=====================================================================")

    if not target_registry:
        print(f"\n⚠️ No thermostats matching keywords or MFR ID {ECOCONTROL_MFR_ID} detected in range.")
        return

    print(f"\n🚀 STAGE 2: Found {len(target_registry)} device(s). Moving to active connections...")
    for device, passive_data in target_registry:
        await read_device_active_data(device, passive_data)
    print("\n========================= DIAGNOSTIC COMPLETE =========================")

if __name__ == "__main__":
    asyncio.run(main())
