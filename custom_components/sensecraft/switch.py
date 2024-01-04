from __future__ import annotations

import logging
from typing import Any
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from .core.sscma_local import SScmaLocal
from .const import (
    DOMAIN,
    SSCMA_LOCAL,
    DATA_SOURCE,
    SSCMA,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][config_entry.entry_id]
    data_source = data.get(DATA_SOURCE)
    if data_source == SSCMA:
        local: SScmaLocal = data[SSCMA_LOCAL]
        async_add_entities([
            sscmaSwitch(local.deviceId, local.deviceName,
                        local.trace, config_entry.entry_id, "Trace"),
            sscmaSwitch(local.deviceId, local.deviceName,
                        local.heatmap, config_entry.entry_id, "HeatMap")
        ])


class sscmaSwitch(SwitchEntity):
    def __init__(
        self,
        id: str,
        name: str,
        state: bool,
        entry_id: str,
        switch_type: str,
    ) -> None:
        self._id = id
        self._device_name = name
        self._entry_id = entry_id
        self._attr_name = switch_type
        number = name.split("_")[-1]
        self._model = name.removesuffix("_" + number)
        self._attr_unique_id = id + "_" + switch_type.lower()
        self._switch_type = switch_type
        self._attr_is_on = state

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._id)},
            name=self._device_name,
            manufacturer="Seeed Studio",
            model=self._model,
            sw_version="1.0",
        )

    def turn_on(self, **kwargs: Any) -> None:
        data = self.hass.data[DOMAIN][self._entry_id]
        local: SScmaLocal = data[SSCMA_LOCAL]
        if local is not None:
            setattr(local, self._switch_type.lower(), True)
            self._attr_is_on = True
            self.async_write_ha_state()

    def turn_off(self, **kwargs: Any) -> None:
        data = self.hass.data[DOMAIN][self._entry_id]
        local: SScmaLocal = data[SSCMA_LOCAL]
        if local is not None:
            setattr(local, self._switch_type.lower(), False)
            self._attr_is_on = False
            self.async_write_ha_state()
