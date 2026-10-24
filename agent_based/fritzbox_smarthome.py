#!/usr/bin/env python3

import json

from cmk.agent_based.v2 import (
    AgentSection,
    CheckPlugin,
    Metric,
    Result,
    Service,
    State,
    check_levels,
)

# Raw hkr temperature values with a special meaning (unit: 0.5 °C)
HKR_TEMP_OFF = 253      # "Aus" / summer mode
HKR_TEMP_ON = 254       # "An" / maximum
HKR_TEMP_INVALID = 255  # not available


def detect_device_type(fbm):
    fbm = int(fbm)
    if fbm >> 0 & 1:
        return "HANFUNDevice"
    if fbm >> 13 & 1:
        return "HANFUNUnit"
    if fbm >> 4 & 1:
        return "AlarmSensor"
    if fbm >> 5 & 1:
        return "Button"
    if fbm >> 6 & 1:
        return "Thermostat"
    if fbm >> 9 & 1:
        return "Switch"
    if fbm >> 7 & 1:
        return "Powermeter"
    if fbm >> 10 & 1:
        return "DECTRepeater"
    if fbm >> 8 & 1:
        return "TemperatureSensor"
    if fbm >> 11 & 1:
        return "Microphone"
    if fbm >> 2 & 1 or fbm >> 17 & 1:
        return "Light"
    return "SmarthomeDevice"


def parse_fritzbox_smarthome(string_table):
    # the agent uses sep(0), so every line is a single column
    data = json.loads("".join(line[0] for line in string_table if line))
    if not isinstance(data, list):
        return []
    return data


def discover_fritzbox_smarthome(section):
    for dev in section:
        dev_type = detect_device_type(dev.get("functionbitmask", 0))
        # HAN-FUN units are sub units of a HAN-FUN device and carry no data
        # of their own, the interesting values are on the parent device.
        if dev_type == "HANFUNUnit":
            continue
        name = f"{dev_type} {dev['id']} {dev['name']}"
        yield Service(item=name, parameters={})


default_params = {
    "present": "warn",
    "hkr": {
        "hkr_bat_always": True,
        "hkr_warn": {
            "hkr_diff_soll": 5.0,
            "hkr_bat_below": 50,
        },
        "hkr_crit": {
            "hkr_diff_soll": 10.0,
            "hkr_bat_below": 30,
        },
    },
    "humidity": {
        "humidity_warn": {
            "higher_than": 60,
            "lower_than": 40,
        },
        "humidity_crit": {
            "higher_than": 70,
            "lower_than": 30,
        },
    },
}


def _hkr_temp(raw):
    """Convert a raw hkr temperature (0.5 °C steps) to °C, None for special values."""
    if raw is None:
        return None
    raw = int(raw)
    if raw >= HKR_TEMP_OFF:
        return None
    return raw / 2.0


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _check_hkr(h, params):
    hkr_params = params.get("hkr", default_params["hkr"])
    warn_p = hkr_params.get("hkr_warn", {})
    crit_p = hkr_params.get("hkr_crit", {})
    warn_diff = warn_p.get("hkr_diff_soll", 5.0)
    crit_diff = crit_p.get("hkr_diff_soll", 10.0)
    warn_bat = warn_p.get("hkr_bat_below", 50)
    crit_bat = crit_p.get("hkr_bat_below", 30)

    # --- battery ---
    battery = h.get("battery")
    if battery is not None:
        battery = _to_int(battery)
        if battery < crit_bat:
            yield Result(state=State.CRIT, summary=f"Battery critically low: {battery}%")
        elif battery < warn_bat:
            yield Result(state=State.WARN, summary=f"Battery low: {battery}%")
        if hkr_params.get("hkr_bat_always", False):
            yield Metric("battery", battery, boundaries=(0, 100))
    elif _to_int(h.get("batterylow")) == 1:
        yield Result(state=State.WARN, summary="Battery low")

    # --- temperature ---
    tist = _hkr_temp(h.get("tist"))
    if tist is None:
        yield Result(state=State.WARN, summary="Temperature not available")
    else:
        yield Metric("temp_actual", tist)
        yield Result(state=State.OK, summary=f"Temperature: {tist}°C")

    # --- target temperature / deviation ---
    # In summer mode or when the thermostat is set to "off"/"on" tsoll has no
    # numerical meaning (253/254), so no target metric and no deviation check.
    summer = _to_int(h.get("summeractive")) == 1
    tsoll = _hkr_temp(h.get("tsoll"))
    if summer:
        yield Result(state=State.OK, summary="Summer mode")
    elif tsoll is None:
        yield Result(state=State.OK, summary="Target: " + ("on" if _to_int(h.get("tsoll")) == HKR_TEMP_ON else "off"))
    else:
        yield Metric("temp_target", tsoll)
        if tist is not None:
            diff = abs(tsoll - tist)
            if diff > crit_diff:
                yield Result(state=State.CRIT, summary=f"Target: {tsoll}°C, deviation too high: {diff}K")
            elif diff > warn_diff:
                yield Result(state=State.WARN, summary=f"Target: {tsoll}°C, deviation: {diff}K")
            else:
                yield Result(state=State.OK, summary=f"Target: {tsoll}°C")

    komfort = _hkr_temp(h.get("komfort"))
    if komfort is not None:
        yield Metric("temp_comfort", komfort)
    absenk = _hkr_temp(h.get("absenk"))
    if absenk is not None:
        yield Metric("temp_eco", absenk)

    # --- window open detection ---
    wo = _to_int(h.get("windowopenactiv"))
    yield Metric("window_open", wo)
    if wo == 1:
        yield Result(state=State.OK, summary="Window open")

    # --- error state reported by the thermostat ---
    errorcode = _to_int(h.get("errorcode"))
    if errorcode != 0:
        yield Result(state=State.WARN, summary=f"Thermostat error code {errorcode}")


def _check_humidity(hum, params):
    rh = _to_int(hum.get("rel_humidity"))
    yield Metric("humidity", rh, boundaries=(0, 100))

    hum_params = params.get("humidity", default_params["humidity"])
    hwarn = hum_params.get("humidity_warn", {})
    hcrit = hum_params.get("humidity_crit", {})
    warn_high = hwarn.get("higher_than", 60)
    warn_low = hwarn.get("lower_than", 40)
    crit_high = hcrit.get("higher_than", 70)
    crit_low = hcrit.get("lower_than", 30)

    if rh > crit_high or rh < crit_low:
        yield Result(state=State.CRIT, summary=f"Humidity critical: {rh}%")
    elif rh > warn_high or rh < warn_low:
        yield Result(state=State.WARN, summary=f"Humidity warning: {rh}%")
    else:
        yield Result(state=State.OK, summary=f"Humidity: {rh}%")


def _check_powermeter(pm):
    for key, metric, factor, unit, fmt in (
        ("power", "power", 1000.0, "W", "{:.2f}"),
        ("energy", "energy", 1000.0, "kWh", "{:.2f}"),
        ("voltage", "voltage", 1000.0, "V", "{:.1f}"),
    ):
        raw = pm.get(key)
        if raw is None:
            yield Result(state=State.WARN, summary=f"{key.capitalize()} not available")
            continue
        value = float(raw) / factor
        yield Metric(metric, value)
        yield Result(state=State.OK, summary=f"{key.capitalize()}: {fmt.format(value)}{unit}")


def check_fritzbox_smarthome(item, params, section):
    params = params or default_params

    dev_id = item.split(" ")[1]
    dev = next((d for d in section if d["id"] == dev_id), None)
    if not dev:
        yield Result(state=State.CRIT, summary="Device not found")
        return

    # --- offline handling ---
    present_param = str(params.get("present", "warn"))
    if dev.get("present") != "1":
        state = {"ok": State.OK, "warn": State.WARN, "crit": State.CRIT}.get(present_param, State.WARN)
        yield Result(state=state, summary="Device not present")
        return

    summary = f"{dev.get('manufacturer', '?')} {dev.get('productname', '?')} ({dev.get('name', '?')})"
    yield Result(state=State.OK, summary=summary)

    data = dev.get("data", {})
    is_hkr = "hkr" in data

    # --- thermostat (HKR) ---
    if is_hkr:
        yield from _check_hkr(data["hkr"], params)

    # --- humidity ---
    if "humidity" in data:
        yield from _check_humidity(data["humidity"], params)

    # --- temperature sensor of non-thermostat devices (switches, buttons, ...) ---
    # Thermostats report the same value in hkr/tist, so skip it there.
    if "temperature" in data and not is_hkr:
        celsius = data["temperature"].get("celsius")
        if celsius is not None:
            temp_params = params.get("temperature", {})
            yield from check_levels(
                float(celsius) / 10.0,
                levels_upper=temp_params.get("levels_upper"),
                levels_lower=temp_params.get("levels_lower"),
                metric_name="temperature",
                label="Temperature",
                render_func=lambda v: f"{v:.1f}°C",
            )

    # --- battery of non-thermostat devices (thermostats are handled above) ---
    if not is_hkr:
        battery = dev.get("battery")
        if battery is not None:
            yield Metric("battery", _to_int(battery), boundaries=(0, 100))
        if _to_int(dev.get("batterylow")) == 1:
            yield Result(state=State.WARN, summary=f"Battery low: {battery}%" if battery is not None else "Battery low")
        elif battery is not None:
            yield Result(state=State.OK, summary=f"Battery: {battery}%")

    # --- door/window contact (alert) ---
    if "alert" in data:
        alert_state = data["alert"].get("state")
        if alert_state is not None:
            st = _to_int(alert_state)
            yield Metric("alert_state", st)
            yield Result(state=State.OK, summary=f"Contact: {'open' if st else 'closed'}")

    # --- switch ---
    if "switch" in data:
        st = data["switch"].get("state", "0")
        mode = data["switch"].get("mode", "unknown")
        yield Metric("switch_state", _to_int(st))
        yield Result(state=State.OK, summary=f"Switch is {'ON' if st == '1' else 'OFF'} ({mode})")

    # --- powermeter ---
    if "powermeter" in data:
        yield from _check_powermeter(data["powermeter"])


agent_section_fritzbox_smarthome = AgentSection(
    name="fritzbox_smarthome",
    parse_function=parse_fritzbox_smarthome,
)

check_plugin_fritzbox_smarthome = CheckPlugin(
    name="fritzbox_smarthome",
    service_name="%s",
    discovery_function=discover_fritzbox_smarthome,
    check_function=check_fritzbox_smarthome,
    check_default_parameters=default_params,
    check_ruleset_name="fritzbox_smarthome",
)
