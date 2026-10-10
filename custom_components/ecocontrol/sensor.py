"""Sensor entities for the read-only ecoControl integration."""

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
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

# Clean mapping structure using native Home Assistant descriptions directly
SENSOR_DEFINITIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="air_temp",
        name="Air temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="floor_temp",
        name="Floor temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="desired_temp",
        name="Desired temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="error_code",
        name="Error code",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="operation_mode",
        name="Operational mode",
        icon="mdi:calendar-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="relay_cycles",
        name="Relay cycle count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="clicks",
        icon="mdi:toggle-switch",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="operating_hours",
        name="Total operating time",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="heating_hours",
        name="Accumulated heating duration",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        icon="mdi:chart-timeline-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ecoControl sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data["address"]
    fallback_name = entry.data["default_name"]

    async_add_entities(
        EcoControlSensor(
            coordinator=coordinator,
            address=address,
            fallback_name=fallback_name,
            description=description,
        )
        for description in SENSOR_DEFINITIONS
    )


class EcoControlSensor(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]],
    SensorEntity,
):
    """Representation of one read-only ecoControl sensor."""

    entity_description: SensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        address: str,
        fallback_name: str,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize an ecoControl sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self.address = address
        self.fallback_name = fallback_name

        mac_clean = address.replace(":", "").lower()
        self._attr_unique_id = f"ecocontrol_{mac_clean}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the current sensor value directly matching description keys."""
        if self.coordinator.data is None:
            return None
            
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def device_info(self) -> DeviceInfo:
        """Bind the entity to the ecoControl thermostat device."""
        if self.coordinator.data:
            name = self.coordinator.data.get("name", self.fallback_name)
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
