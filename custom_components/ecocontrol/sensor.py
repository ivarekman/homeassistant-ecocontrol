"""Sensor entities for the read-only ecoControl integration."""

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import DOMAIN

SENSOR_DEFINITIONS = [
    {
        "name": "Air temperature",
        "key": "air_temp",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
    },
    {
        "name": "Floor temperature",
        "key": "floor_temp",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
    },
    {
        "name": "Desired temperature",
        "key": "desired_temp",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
    },
    {
        "name": "Error code",
        "key": "error_code",
        "device_class": None,
        "unit": None,
    },
    {
        "name": "Hardware version",
        "key": "hw_version",
        "device_class": None,
        "unit": None,
    },
    {
        "name": "Software version",
        "key": "software_version",
        "device_class": None,
        "unit": None,
    },
    {
        "name": "Serial number",
        "key": "serial",
        "device_class": None,
        "unit": None,
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
            unit=definition["unit"],
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
        unit: str | None = None,
    ) -> None:
        """Initialize an ecoControl sensor interface."""
        super().__init__(coordinator)

        self._key = key
        self.address = address
        self.fallback_name = fallback_name
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit

        mac_clean = address.replace(":", "").lower()
        self._attr_unique_id = f"ecocontrol_{mac_clean}_{key}"

    @property
    def native_value(self) -> Any:
        """Return the state value computed out of our memory update coordinator."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._key)

    @property
    def device_info(self) -> DeviceInfo:
        """Binds all sensor entities into one unified primary device card pane."""
        mac_clean = self.address.replace(":", "").lower()
        name = self.coordinator.data.get("name", self.fallback_name) if self.coordinator.data else self.fallback_name
        return DeviceInfo(
            identifiers={(DOMAIN, f"ecocontrol_{mac_clean}")},
            name=name,
            manufacturer="Taelek Oy",
            model="ecoControl Thermostat",
        )
