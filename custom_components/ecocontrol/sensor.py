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
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
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
        "name": "Error code",
        "key": "error_code",
        "device_class": None,
        "state_class": None,
        "unit": None,
        "icon": "mdi:alert-circle-outline",
        "category": EntityCategory.DIAGNOSTIC,
    },
    {
        "name": "Operational mode",
        "key": "operation_mode",
        "device_class": None,
        "state_class": None,
        "unit": None,
        "icon": "mdi:calendar-clock",
        "category": EntityCategory.DIAGNOSTIC,
    },
    {
        "name": "Relay cycle count",
        "key": "relay_cycles",
        "device_class": None,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "unit": "clicks",
        "icon": "mdi:toggle-switch",
        "category": EntityCategory.DIAGNOSTIC,
    },
    {
        "name": "Total operating time",
        "key": "operating_hours",
        "device_class": SensorDeviceClass.DURATION,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "unit": UnitOfTime.HOURS,
        "icon": "mdi:clock-outline",
        "category": EntityCategory.DIAGNOSTIC,
    },
    {
        "name": "Accumulated heating duration",
        "key": "heating_hours",
        "device_class": SensorDeviceClass.DURATION,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "unit": UnitOfTime.HOURS,
        "icon": "mdi:chart-timeline-variant",
        "category": EntityCategory.DIAGNOSTIC,
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ecoControl sensors from a config entry."""

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
            category=definition.get("category", None),
        )
        for definition in SENSOR_DEFINITIONS
    ]

    async_add_entities(entities)


class EcoControlSensor(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]],
    SensorEntity,
):
    """Representation of one read-only ecoControl sensor."""

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
        category: EntityCategory | None = None,
    ) -> None:
        """Initialize an ecoControl sensor."""

        super().__init__(coordinator)

        self._key = key
        self.address = address
        self.fallback_name = fallback_name

        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_entity_category = category

        mac_clean = address.replace(":", "").lower()
        self._attr_unique_id = f"ecocontrol_{mac_clean}_{key}"

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""

        if self.coordinator.data is None:
            return None
            
        return self.coordinator.data.get(self._key)

    @property
    def device_info(self) -> DeviceInfo:
        """Bind the entity to the ecoControl thermostat device."""

        if self.coordinator.data:
            name = self.coordinator.data.get(
                "name",
                self.fallback_name,
            )
            hardware_version = self.coordinator.data.get("hw_version")
            software_version = self.coordinator.data.get("software_version")
            serial_number = self.coordinator.data.get("serial")
        else:
            name = self.fallback_name
            hardware_version = None
            software_version = None
            serial_number = None

        return DeviceInfo(
            identifiers={(DOMAIN, self.address)}, 
            name=name,
            manufacturer="Taelek Oy",
            model="ecoControl Thermostat",
            serial_number=serial_number,
            hw_version=hardware_version,
            sw_version=software_version,
        )