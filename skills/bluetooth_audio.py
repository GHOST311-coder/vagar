"""Bluetooth audio device management for Vagar.

Voice tools:
  list_audio_devices   - show playback + recording endpoints, flag Bluetooth ones
  set_audio_device     - switch Windows default playback/recording device by name
  current_audio_device - show the active playback + recording devices

IMPORTANT ARCHITECTURE NOTE:
  Vagar's live voice runs over LiveKit to the phone app. Bluetooth headphones
  or Meta glasses PAIRED TO THE PHONE route automatically through Android's
  audio system — no setup needed, it just works. These tools manage the
  LAPTOP's Windows audio endpoints instead (local playback, testing, or any
  future local voice mode).

  Meta glasses pair as a standard Bluetooth headset (speaker + mic). Their
  camera and Meta AI features are locked to Meta's own app — no public API
  exists, so those are out of scope.

Switching uses the standard IPolicyConfig COM interface (the same mechanism
Windows Settings uses). Safe to call; it only changes the default endpoint.
"""

try:
    from livekit.agents.llm import function_tool
except ImportError:  # pragma: no cover - allows unit testing off-laptop
    def function_tool(*_a, **_k):
        def _deco(f):
            return f
        return _deco

import re

_BT_HINTS = ("bluetooth", "a2dp", "le audio", "ray-ban")


def _bluetooth_device_names():
    """Names of audio endpoints whose PnP ID is on the Bluetooth enumerator."""
    try:
        import subprocess
        ps = ("Get-PnpDevice -Class AudioEndpoint | Where-Object { $_.DeviceID "
              "-like '*BTHENUM*' } | Select-Object -ExpandProperty FriendlyName")
        out = subprocess.run(["powershell", "-noprofile", "-c", ps],
                             capture_output=True, text=True, timeout=30)
        return {l.strip().lower() for l in out.stdout.splitlines() if l.strip()}
    except Exception:
        return set()


def _looks_bluetooth(name, bt_names=None):
    nl = (name or "").lower()
    if any(h in nl for h in _BT_HINTS):
        return True
    # "headset"/"hands-free" alone isn't enough (wired jacks use those names);
    # confirm via the PnP Bluetooth enumerator.
    if bt_names is None:
        bt_names = _bluetooth_device_names()
    if ("headset" in nl or "hands-free" in nl or "handsfree" in nl) and nl in bt_names:
        return True
    return nl in bt_names


def _pycaw():
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities


def _enum_ids_by_flow():
    """Return (render_ids, capture_ids) sets of active endpoint IDs."""
    from comtypes import CoCreateInstance, CLSCTX_ALL
    from pycaw.pycaw import IMMDeviceEnumerator
    from pycaw.constants import CLSID_MMDeviceEnumerator, EDataFlow, DEVICE_STATE
    enumerator = CoCreateInstance(
        CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)

    def _ids(flow):
        coll = enumerator.EnumAudioEndpoints(flow, DEVICE_STATE.ACTIVE.value)
        out = set()
        for i in range(coll.GetCount()):
            try:
                out.add(coll.Item(i).GetId())
            except Exception:
                pass
        return out

    return (_ids(EDataFlow.eRender.value), _ids(EDataFlow.eCapture.value))


def _all_devices():
    """List of dicts: id, name, flow (playback/recording), state, bluetooth."""
    AudioUtilities = _pycaw()
    try:
        render_ids, capture_ids = _enum_ids_by_flow()
    except Exception:
        render_ids, capture_ids = set(), set()
    bt_names = _bluetooth_device_names()
    devices = []
    for d in AudioUtilities.GetAllDevices():
        try:
            name = d.FriendlyName
            did = d.id
            state = str(d.state).split(".")[-1]
        except Exception:
            continue
        if did in render_ids:
            flow = "playback"
        elif did in capture_ids:
            flow = "recording"
        else:
            flow = "unknown"
        devices.append({
            "id": did,
            "name": name,
            "flow": flow,
            "state": state,
            "bluetooth": _looks_bluetooth(name, bt_names),
        })
    return devices


def _default_names():
    """(speaker_name, mic_name) for the current default endpoints."""
    AudioUtilities = _pycaw()
    devices = {d["id"]: d["name"] for d in _all_devices()}

    def _resolve(getter):
        try:
            dev = getter()
        except Exception:
            return "unknown"
        # pycaw AudioDevice wrapper: .FriendlyName property
        try:
            val = dev.FriendlyName
            if val:
                return val
        except Exception:
            pass
        # raw IMMDevice pointer: GetId() method, then map to name
        try:
            did = dev.GetId()
            if did and did in devices:
                return devices[did]
        except Exception:
            pass
        # AudioDevice wrapper: .id attribute, then map to name
        try:
            did = dev.id
            if did and did in devices:
                return devices[did]
        except Exception:
            pass
        return "unknown"

    return (_resolve(AudioUtilities.GetSpeakers),
            _resolve(AudioUtilities.GetMicrophone))


def _set_default_endpoint(device_id, flow):
    """Set the default endpoint for console+multimedia roles. Returns True/False."""
    from comtypes import CoCreateInstance, CLSCTX_ALL, GUID, IUnknown, COMMETHOD, HRESULT
    from ctypes import c_int, c_wchar_p, c_void_p, c_int64, POINTER

    class IPolicyConfig(IUnknown):
        _iid_ = GUID('{F8679F50-3C68-4579-9E77-91B5F7D84904}')
        _methods_ = (
            COMMETHOD([], HRESULT, 'GetMixFormat',
                      (['in'], c_wchar_p, 'pszDeviceName'),
                      (['out'], POINTER(c_void_p), 'ppFormat')),
            COMMETHOD([], HRESULT, 'GetDeviceFormat',
                      (['in'], c_wchar_p, 'pszDeviceName'),
                      (['in'], c_int, 'bShared'),
                      (['out'], POINTER(c_void_p), 'ppFormat')),
            COMMETHOD([], HRESULT, 'ResetDeviceFormat',
                      (['in'], c_wchar_p, 'pszDeviceName')),
            COMMETHOD([], HRESULT, 'SetDeviceFormat',
                      (['in'], c_wchar_p, 'pszDeviceName'),
                      (['in'], POINTER(c_void_p), 'pEndpointFormat'),
                      (['in'], POINTER(c_void_p), 'pMixFormat')),
            COMMETHOD([], HRESULT, 'GetProcessingPeriod',
                      (['in'], c_wchar_p, 'pszDeviceName'),
                      (['in'], c_int, 'bShared'),
                      (['out'], POINTER(c_int64), 'pmftDefaultPeriod'),
                      (['out'], POINTER(c_int64), 'pmftMinimumPeriod')),
            COMMETHOD([], HRESULT, 'SetProcessingPeriod',
                      (['in'], c_wchar_p, 'pszDeviceName'),
                      (['in'], POINTER(c_void_p), 'pmftPeriod')),
            COMMETHOD([], HRESULT, 'GetShareMode',
                      (['in'], c_wchar_p, 'pszDeviceName'),
                      (['out'], POINTER(c_void_p), 'pMode')),
            COMMETHOD([], HRESULT, 'SetShareMode',
                      (['in'], c_wchar_p, 'pszDeviceName'),
                      (['in'], POINTER(c_void_p), 'pMode')),
            COMMETHOD([], HRESULT, 'GetPropertyValue',
                      (['in'], c_wchar_p, 'pszDeviceName'),
                      (['in'], POINTER(c_void_p), 'key'),
                      (['out'], POINTER(c_void_p), 'pv')),
            COMMETHOD([], HRESULT, 'SetPropertyValue',
                      (['in'], c_wchar_p, 'pszDeviceName'),
                      (['in'], POINTER(c_void_p), 'key'),
                      (['in'], POINTER(c_void_p), 'pv')),
            COMMETHOD([], HRESULT, 'SetDefaultEndpoint',
                      (['in'], c_wchar_p, 'wszDeviceId'),
                      (['in'], c_int, 'role')),
            COMMETHOD([], HRESULT, 'SetEndpointVisibility',
                      (['in'], c_wchar_p, 'wszDeviceId'),
                      (['in'], c_int, 'bVisible')),
        )

    policy = CoCreateInstance(
        GUID('{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}'),
        interface=IPolicyConfig, clsctx=CLSCTX_ALL)
    # eConsole=0, eMultimedia=1 — set both so apps follow the switch.
    for role in (0, 1):
        hr = policy.SetDefaultEndpoint(device_id, role)
        if hr != 0:
            return False
    return True


def _find_device(name):
    """Fuzzy match by name. Returns (device, error_message)."""
    devices = [d for d in _all_devices() if d["state"] == "Active"]
    nl = (name or "").strip().lower()
    if not nl:
        return None, "Tell me which device to switch to."
    exact = [d for d in devices if d["name"].lower() == nl]
    if len(exact) == 1:
        return exact[0], None
    partial = [d for d in devices if nl in d["name"].lower()]
    if len(partial) == 1:
        return partial[0], None
    if len(partial) > 1:
        names = ", ".join(d["name"] for d in partial)
        return None, f"Multiple matches: {names}. Be more specific."
    names = ", ".join(f'{d["name"]} ({d["flow"]})' for d in devices)
    return None, f"No active device matches '{name}'. Available: {names or 'none'}."


@function_tool()
def list_audio_devices() -> str:
    """List the laptop's audio playback and recording devices, flagging Bluetooth ones.

    Note: Vagar's live voice goes to the phone over LiveKit — Bluetooth gear
    paired to the phone routes automatically. This lists the LAPTOP's endpoints.
    """
    try:
        devices = _all_devices()
    except Exception as e:
        return f"Couldn't enumerate audio devices: {e}"
    if not devices:
        return "No audio devices found."
    lines = []
    for d in devices:
        tag = "[Bluetooth]" if d["bluetooth"] else ""
        lines.append(f'- {d["name"]} ({d["flow"]}, {d["state"]}) {tag}'.rstrip())
    bt = [d for d in devices if d["bluetooth"] and d["state"] == "Active"]
    tail = ""
    if not bt:
        tail = ("\nNo Bluetooth audio device is currently connected to the laptop. "
                "Pair one in Windows Bluetooth settings and it will show up here. "
                "Bluetooth gear paired to your phone works with Vagar automatically.")
    return "Laptop audio devices:\n" + "\n".join(lines) + tail


@function_tool()
def current_audio_device() -> str:
    """Show the laptop's current default speaker and microphone."""
    try:
        spk, mic = _default_names()
        return f"Current laptop audio — speaker: {spk}, microphone: {mic}."
    except Exception as e:
        return f"Couldn't read the current devices: {e}"


@function_tool()
def set_audio_device(name: str) -> str:
    """Switch the laptop's default speaker to the named device.

    name: (part of) the device name, e.g. 'headphones' or 'Realtek'.
    Matches fuzzily; if several match you'll be asked to be specific.
    Only switches playback (speakers). The mic stays put unless you ask.

    Note: on this Windows build the programmatic switch may be refused by
    the OS; if so you'll get the 10-second manual path instead.
    """
    dev, err = _find_device(name)
    if err:
        return err
    if dev["flow"] == "recording":
        return (f"'{dev['name']}' is a microphone, not a speaker. "
                "I only switch playback devices.")
    try:
        ok = _set_default_endpoint(dev["id"], "playback")
    except Exception as e:
        return (_switch_fallback(dev["name"], str(e)))
    if ok:
        bt = " (Bluetooth)" if dev["bluetooth"] else ""
        return f"Laptop speaker is now '{dev['name']}'{bt}."
    return _switch_fallback(dev["name"], "Windows refused the request")


def _switch_fallback(name, reason):
    return (f"I couldn't switch the laptop speaker to '{name}' programmatically "
            f"({reason}). The quick manual path: press Win+I, go to System > Sound, "
            f"and pick '{name}' under Output. (Bluetooth gear paired to your phone "
            f"needs no switching at all — it routes automatically.)")


@function_tool()
def set_audio_mic(name: str) -> str:
    """Switch the laptop's default microphone to the named device.

    name: (part of) the device name, e.g. 'headset' or 'microphone'.

    Note: on this Windows build the programmatic switch may be refused by
    the OS; if so you'll get the 10-second manual path instead.
    """
    dev, err = _find_device(name)
    if err:
        return err
    if dev["flow"] == "playback":
        return (f"'{dev['name']}' is a speaker, not a microphone. "
                "I only switch microphones here.")
    try:
        ok = _set_default_endpoint(dev["id"], "recording")
    except Exception as e:
        return (_switch_fallback(dev["name"], str(e)))
    if ok:
        bt = " (Bluetooth)" if dev["bluetooth"] else ""
        return f"Laptop microphone is now '{dev['name']}'{bt}."
    return _switch_fallback(dev["name"], "Windows refused the request")
