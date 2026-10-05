import asyncio
import logging
import struct
from typing import Any, Tuple, Dict
from bleak import BleakScanner, BleakClient

# ==========================================
# CONSTANTS & FILTER CRITERIA
# ==========================================
TARGET_KEYWORDS = ["tael", "tsense"]
ECOCONTROL_MFR_ID = 1162

UUID_NAME = "2be32db1-5f6b-4cbd-8833-8d6dfb164900"
UUID_HW = "2be32db1-5f6b-4cbd-8813-8d6dfb164900"
UUID_SERIAL_SETPOINT = "2be32db1-5f6b-5bd8-8238-d6dfb1649000"
UUID_DETAILS = "2be32db1-5f6b-4cbd-8843-8d6dfb164900"
UUID_STAT_8863 = "2be32db1-5f6b-4cbd-8863-8d6dfb164900"

# ANSI Terminal Styling Color Codes
CLR_HEADER = "\033[95m"
CLR_TARGET = "\033[92m"  # Green
CLR_SKIP = "\033[90m"    # Grey
CLR_INFO = "\033[94m"    # Blue
CLR_WARN = "\033[93m"    # Yellow
CLR_RESET = "\033[0m"

# ==========================================
# PORTABLE PARSING FUNCTIONS (Home Assistant Ready)
# ==========================================

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
        return clean_bytes_to_string(mfr_bytes[8:])
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
    """Parses raw GATT binary arrays into a clean state dictionary."""
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
    
    # Heating relay state derived bitwise from the passive flag register mask
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


# ==========================================
# SCANNER AND ANALYSIS CORE EXECUTION ENGINE
# ==========================================

async def main():
    # ----------------------------------------------------
    # PHASE 1: BROAD PASSIVE SCAN AND FILTER GRAPH
    # ----------------------------------------------------
    print(f"\n{CLR_HEADER}🔎 PHASE 1: Running Passive Environment Discovery Scan (5 Seconds)...{CLR_RESET}")
    discovered_raw = await BleakScanner.discover(timeout=5.0, return_adv=True)
    
    selected_targets: Dict[str, Tuple[Any, Any]] = {}
    
    print(f"\n📡 Discovered Devices Inventory Breakdown:")
    print("-" * 85)
    for address, (device, adv) in discovered_raw.items():
        name = device.name or adv.local_name or "Unknown Name"
        name_lower = name.lower()
        
        # Check matching parameters against validation keys
        is_matched = any(k in name_lower for k in TARGET_KEYWORDS) or (ECOCONTROL_MFR_ID in adv.manufacturer_data)
        
        if is_matched:
            selected_targets[address] = (device, adv)
            print(f"{CLR_TARGET}🎯 [SELECTED] '{name}' | MAC: {address} | RSSI: {adv.rssi}dBm | Manufacturer IDs: {list(adv.manufacturer_data.keys())}{CLR_RESET}")
        else:
            print(f"{CLR_SKIP}   [SKIPPED]  '{name}' | MAC: {address} | RSSI: {adv.rssi}dBm{CLR_RESET}")
    print("-" * 85)
    print(f"Total Discovered: {len(discovered_raw)} | {CLR_TARGET}Matching Targets Filtered: {len(selected_targets)}{CLR_RESET}")

    if not selected_targets:
        print(f"\n{CLR_WARN}⚠️ Termination Abort: No valid ecoControl target thermostats located in radio spectrum bounds.{CLR_RESET}\n")
        return

    # ----------------------------------------------------
    # PHASE 2: ISOLATED PASSIVE PAYLOAD UNPACK
    # ----------------------------------------------------
    print(f"\n{CLR_HEADER}📦 PHASE 2: Breaking Down Isolated Passive Over-the-Air Frames...{CLR_RESET}")
    
    for address, (device, adv) in selected_targets.items():
        print(f"\n📰 Device passive payload breakdown: {CLR_TARGET}{device.name or 'Tael'}{CLR_RESET} [{address}]")
        print("  " + "~"*60)
        
        if ECOCONTROL_MFR_ID in adv.manufacturer_data:
            payload = adv.manufacturer_data[ECOCONTROL_MFR_ID]
            
            # Extract metrics using modular logic blocks
            p_name = parse_name_from_mfr(payload) or "Unknown Format"
            p_floor = parse_floor_temp_from_mfr(payload)
            p_flag = payload[2] if len(payload) >= 3 else 0
            is_heating_active = bool(p_flag & 0x80)
            
            print(f"  {CLR_INFO}► INTERPRETED PASSIVE DATA:{CLR_RESET}")
            print(f"    ├── Broadcasted Identification Tag : {p_name}")
            print(f"    ├── Extracted Floor Temperature    : {p_floor if p_floor is not None else '-'}°C")
            print(f"    └── Inferred Heating Relay State   : {'🔥 Active (Heating)' if is_heating_active else '❄️ Idle (Balanced)'}")
            print(f"  {CLR_INFO}► RAW DATA ARRAYS:{CLR_RESET}")
            print(f"    ├── Payload Hex Length String      : {payload.hex()}")
            print(f"    └── Decimal Int Representation     : {list(payload)}")
        else:
            print(f"  {CLR_WARN}⚠️ Structural Warning: Target parsed based on name, but lacks specific Manufacturer Data ID block definitions.{CLR_RESET}")
        print("  " + "~"*60)

    # ----------------------------------------------------
    # PHASE 3: ACTIVE GATT CORRELATION PASS
    # ----------------------------------------------------
    print(f"\n{CLR_HEADER}🔗 PHASE 3: Connecting to Targets & Generating Comparative Analysis...{CLR_RESET}")
    
    for address, (device, adv) in selected_targets.items():
        print(f"\n⚙️ Initializing dynamic socket pass to: {CLR_TARGET}{device.name or 'Tael'}{CLR_RESET} [{address}]")
        print("  " + "="*70)
        
        payload = adv.manufacturer_data.get(ECOCONTROL_MFR_ID, b"")
        p_name = parse_name_from_mfr(payload) or "N/A"
        p_floor = parse_floor_temp_from_mfr(payload)
        p_flag = payload[2] if len(payload) >= 3 else 0
        p_heating = bool(p_flag & 0x80)
        
        try:
            async with BleakClient(device, timeout=8.0) as client:
                print(f"  ✅ Connected successfully! Reading active registers...")
                
                # Retrieve direct characteristic buffers
                raw_name = await client.read_gatt_char(UUID_NAME)
                raw_hw = await client.read_gatt_char(UUID_HW)
                raw_serial = await client.read_gatt_char(UUID_SERIAL_SETPOINT)
                raw_details = await client.read_gatt_char(UUID_DETAILS)
                
                raw_8863 = b""
                try: 
                    raw_8863 = await client.read_gatt_char(UUID_STAT_8863)
                except Exception: 
                    pass
                
                # Execute full state packaging parse rules using the modular helper
                parsed = parse_thermostat_payload(raw_name, raw_hw, raw_serial, raw_details, raw_8863, "ecoControl", p_flag)
                
                print(f"\n  📊 {CLR_INFO}COMPLETE COMBINED PARSING STATE REPORT:{CLR_RESET}")
                print(f"    ├── Hardware Registry String Name : '{parsed['name']}'")
                print(f"    ├── Unpacked Production Serial No : {parsed['serial']}")
                print(f"    ├── Unpacked Firmware Specification: {parsed['hw_version']} (Build v{parsed['software_version']})")
                print(f"    ├── Current System Error Register : {parsed['error_code'] if parsed['error_code'] != 0 else '-'}")
                print(f"    ├── Operation Mode Profile Code   : {parsed['operation_mode']}")
                print(f"    ├── High-Res Room Air Temperature : {parsed['air_temp']}°C")
                print(f"    ├── High-Res Room Floor Temp      : {parsed['floor_temp']}°C")
                print(f"    ├── Live Hardware Target Setpoint : {parsed['desired_temp']}°C")
                print(f"    ├── Active Relay Heating State    : {parsed['is_heating']}")
                if parsed['relay_cycles'] is not None:
                    print(f"    ├── Accumulated Operational Stats :")
                    print(f"    │   ├── Total Swapping Cycles     : {parsed['relay_cycles']} clicks")
                    print(f"    │   ├── Active Power-On Runtime   : {parsed['operating_hours']} Hours")
                    print(f"    │   └── Total Physical Heat Time  : {parsed['heating_hours']} Hours")
                
                print(f"\n  🕵️‍♂️ {CLR_HEADER}ACTIVE VS PASSIVE INTEGRITY METRICS DIFFERENCE ANALYSIS:{CLR_RESET}")
                
                # Compute sync and variance thresholds cleanly
                name_delta = "MATCHING (100% Sync)" if p_name == parsed['name'] or parsed['name'].startswith(p_name) else f"⚠️ MISMATCH DETECTED ('{p_name}' vs '{parsed['name']}')"
                temp_delta = 0.0 if p_floor is None or parsed['floor_temp'] is None else round(abs(p_floor - parsed['floor_temp']), 1)
                
                print(f"    ├── Naming Metric Alignment Verification : {name_delta}")
                print(f"    ├── Temperature Deviation Variance Float : {temp_delta}°C (Passive: {p_floor}°C | Active: {parsed['floor_temp']}°C)")
                print(f"    └── Relay Signal Synchronization Matrix  : {'MATCHING (100% Sync)' if p_heating == parsed['is_heating'] else '⚠️ METRIC DELAY DRIFT PRESENT'}")
                
        except Exception as ex:
            print(f"  ❌ {CLR_WARN}[CONNECTION ARTIFACT ERROR] Active GATT transaction failed: {ex}{CLR_RESET}")
            print(f"     ↳ Range bounds dropped below threshold or hardware adapter slots occupied.")
            print(f"     ↳ Fallback State: Rely on the Phase 2 isolated passive values stored above.")
        print("  " + "="*70)

    print(f"\n{CLR_HEADER}=========================== DIAGNOSTIC PIPELINE COMPLETE ==========================={CLR_RESET}\n")

if __name__ == "__main__":
    asyncio.run(main())
