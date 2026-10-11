"""Connected Bluetooth devices provider (spec Actions mode §3 `bt_info`).

WinRT ``Windows.Devices.Enumeration``: ``DeviceInformation.FindAllAsync(CONNECTED_AQS, [IS_CONNECTED],
AssociationEndpoint)`` over the Bluetooth classic and BLE association endpoints, then a filter on the
``System.Devices.Aep.IsConnected`` property. The AQS keeps ``Bluetooth.IssueInquiry:=False`` (the form of
BluetoothDevice.GetDeviceSelectorFromPairingState): without it FindAllAsync starts a Bluetooth inquiry and does not
complete before ~20 s; with it the query answers from the system cache in ~10-30 ms. The call runs on the WinRT
worker (actions.winrt_call), bounded by QUERY_TIMEOUT_S.

Snapshot: ``{"available": True, "connected": [names]}`` (deduplicated, a device paired as classic + BLE is listed
once, sorted without case); ``{"available": False}`` without WinRT. No action; the hub merges it with the radios
provider (see actions.radios.merge_radio_state).
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from actions import winrt_call
from actions.base import ProviderError

_log = logging.getLogger("orizonx.actions.bt_info")

QUERY_TIMEOUT_S = 2.0

PROTOCOL_BLUETOOTH = "{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}"
PROTOCOL_BLUETOOTH_LE = "{bb7bb05e-5972-42b5-94fc-76eaa7084d49}"
IS_CONNECTED = "System.Devices.Aep.IsConnected"
_TRUE = "System.StructuredQueryType.Boolean#True"
_FALSE = "System.StructuredQueryType.Boolean#False"
CONNECTED_AQS = (
    f'(System.Devices.Aep.ProtocolId:="{PROTOCOL_BLUETOOTH}" OR '
    f'System.Devices.Aep.ProtocolId:="{PROTOCOL_BLUETOOTH_LE}") AND '
    f'(System.Devices.Aep.IsPaired:={_TRUE} OR System.Devices.Aep.Bluetooth.IssueInquiry:={_FALSE}) AND '
    f'{IS_CONNECTED}:={_TRUE}')
_KIND_ASSOCIATION_ENDPOINT = 5   # DeviceInformationKind.ASSOCIATION_ENDPOINT


class BluetoothApi(Protocol):
    def endpoints(self) -> list[tuple[str, Optional[bool]]]:
        """[(name, IsConnected or None when the property is missing)] of the Bluetooth/BLE endpoints."""


class WinRTBluetoothApi:
    """The real query, through pywinrt on the WinRT worker thread."""

    def __init__(self, worker: Optional[winrt_call.WinRTWorker] = None) -> None:
        from winrt.system import unbox_boolean  # ImportError -> provider unavailable
        from winrt.windows.devices.enumeration import DeviceInformation, DeviceInformationKind

        self._find = DeviceInformation.find_all_async_with_kind_aqs_filter_and_additional_properties
        self._kind = DeviceInformationKind(_KIND_ASSOCIATION_ENDPOINT)
        self._unbox = unbox_boolean
        self._worker = worker or winrt_call.WORKER

    def endpoints(self) -> list[tuple[str, Optional[bool]]]:
        def query() -> list[tuple[str, Optional[bool]]]:
            found = winrt_call.wait_op(self._find(CONNECTED_AQS, [IS_CONNECTED], self._kind), QUERY_TIMEOUT_S)
            result = []
            for device in found:
                props = device.properties
                connected = self._unbox(props.lookup(IS_CONNECTED)) if props.has_key(IS_CONNECTED) else None
                result.append((device.name, connected))
            return result
        return self._worker.run(query, QUERY_TIMEOUT_S)


def _default_api() -> Optional[BluetoothApi]:
    try:
        return WinRTBluetoothApi()
    except ImportError as e:
        _log.info("bt_info unavailable: %s", e)
        return None


_DEFAULT = object()


class BluetoothInfoProvider:
    """Names of the connected Bluetooth / BLE devices (see the module docstring)."""

    def __init__(self, api: Any = _DEFAULT) -> None:
        self._api: Optional[BluetoothApi] = _default_api() if api is _DEFAULT else api

    def snapshot(self) -> dict:
        if self._api is None:
            return {"available": False}
        try:
            endpoints = self._api.endpoints()
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001 - WinRT error (OSError), timeout
            raise ProviderError(f"bt_info: Bluetooth query failed: {e!r}") from e
        names = {name.strip() for name, connected in endpoints if connected is True and name and name.strip()}
        return {"available": True, "connected": sorted(names, key=lambda n: (n.casefold(), n))}

    def handle(self, action: dict) -> Optional[str]:
        """No action here (bluetooth.set goes to the radios provider): any id is logged and ignored."""
        _log.warning("bt_info: unknown action %r ignored", action.get("id"))
        return None
