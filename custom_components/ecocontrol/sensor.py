"""Sensor entities for the read-only ecoControl integration."""

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import DOMAIN

# 🚀 EXTENDED DEFINITIONS: Keeps your precise list pattern but maps all parameters
SENSOR_DEFINITIONS = [
    {
        "name": "Air temperature",
        "key": "air_temp",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": None,
    },
    {
        "name": "Floor temperature",
        "key": "floor_temp",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": None,
    },
    {
        "name": "Desired temperature",
        "key": "desired_temp",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": None,
    },
    {
        "name": "Heating status",
        "key": "is_heating",
        "device_class": None,
        "state_class": None,
        "unit": None,
        "icon": "mdi:fire",
    },
    {
        "name": "Error code",
        "key": "error_code",
        "device_class": None,
        "state_class": None,
        "unit": None,
        "icon": "mdi:alert-circle-outline",
    },
    {
        "name": "Operational mode",
        "key": "operation_mode",
        "device_class": None,
        "state_class": None,
        "unit": None,
        "icon": "mdi:calendar-clock",
    },
    {
        "name": "Hardware version",
        "key": "hw_version",
        "device_class": None,
        "state_class": None,
        "unit": None,
        "icon": "mdi:chip",
    },
    {
        "name": "Software version",
        "key": "software_version",
        "device_class": None,
        "state_class": None,
        "unit": None,
        "icon": "mdi:xml",
    },
    {
        "name": "Serial number",
        "key": "serial",
        "device_class": None,
        "state_class": None,
        "unit": None,
        "icon": "mdi:numeric",
    },
    {
        "name": "Relay cycle count",
        "key": "relay_cycles",
        "device_class": None,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "unit": "clicks",
        "icon": "mdi:toggle-switch",
    },
    {
        "name": "Total operating time",
        "key": "operating_hours",
        "device_class": SensorDeviceClass.DURATION,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "unit": UnitOfTime.HOURS,
        "icon": "mdi:clock-outline",
    },
    {
        "name": "Accumulated heating duration",
        "key": "heating_hours",
        "device_class": SensorDeviceClass.DURATION,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "unit": UnitOfTime.HOURS,
        "icon": "mdi:chart-timeline-variant",
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ecoControl sensors from a config entry data block handle."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data["address"]
    fallback_name = entry.data["default_name"]

    entities = [
        EcoControlSensor(
            coordinator=coordinator,
            address=address,
            fallback_name=fallback_name,
            name=definition["name"],
            key=definition["key"],
            device_class=definition["device_class"],
            state_class=definition["state_class"],
            unit=definition["unit"],
            icon=definition["icon"],
        )
        for definition in SENSOR_DEFINITIONS
    ]

    async_add_entities(entities)


class EcoControlSensor(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]],
    SensorEntity,
):
    """Representation of one read-only ecoControl sensor parameter state."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        address: str,
        fallback_name: str,
        name: str,
        key: str,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
        unit: str | None = None,
        icon: str | None = None,
    ) -> None:
        """Initialize an ecoControl sensor interface."""
        super().__init__(coordinator)

        self._key = key
        self.address = address
        self.fallback_name = fallback_name
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

        mac_clean = address.replace(":", "").lower()
        self._attr_unique_id = f"ecocontrol_{mac_clean}_{key}"

    @property
    def native_value(self) -> Any:
        """Return the state value computed out of our memory update coordinator."""
        if self.coordinator.data is None:
            return None
        
        val = self.coordinator.data.get(self._key)
        
        # Friendly representation for error code handling
        if self._key == "error_code" and (val == 0 or val is None):
            return "-"
            
        # Friendly string representation for the heating bitmask state variable
        if self._key == "is_heating":
            return "Heating" if val else "Idle"
            
        return val

    @property
    def device_info(self) -> DeviceInfo:
        """Binds all sensor entities into one unified primary device card pane."""
        mac_clean = self.address.replace(":", "").lower()
        name = self.coordinator.data.get("name", self.fallback_name) if self.coordinator.data else self.fallback_name
        
        sw_version = None
        if self.coordinator.data:
            hw = self.coordinator.data.get("hw_version")
            sw = self.coordinator.data.get("software_version")
            if hw and sw:
                sw_version = f"{hw} v{sw}"
            elif hw:
                sw_version = hw

        return DeviceInfo(
            identifiers={(DOMAIN, f"ecocontrol_{mac_clean}")},
            name=name,
            manufacturer="Taelek Oy",
            model="ecoControl Thermostat",
            sw_version=sw_version,
        )
