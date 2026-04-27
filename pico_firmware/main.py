import json
import time

import machine
from machine import I2C, Pin, WDT


SAMPLE_SECONDS = 1.0
TEMP_RH_MEASURE_SECONDS = 2.5
WATCHDOG_TIMEOUT_MS = 8000
DEVICE_NAME = "pico-2-shed"
BOOT_COUNT_FILE = "boot_count.txt"

# Change these pin numbers to match your wiring.
SHT_I2C_ID = 0
SHT_I2C_SDA_PIN = 4
SHT_I2C_SCL_PIN = 5
SHT45_ADDR = 0x44
FLOW_PIN = 16
LIGHTING_PIN = 28
CROSS_AUGER_PIN = 18
AUGER_LEFT_PIN = 20
AUGER_RIGHT_PIN = 22
STATUS_LED_PIN = "LED"
HX711_DOUT_PIN = 14
HX711_SCK_PIN = 15
HX711_READINGS = 8
AUGER_INPUT_ACTIVE_LOW = True

# SHT4x high precision measurement command.
SHT45_MEASURE_HIGH_PRECISION = b"\xFD"

# Hall-effect flow meter calibration.
# Example for common YF-S201-style meters:
#   L/min = pulses_per_second / 7.5
FLOW_HZ_PER_LPM = 7.5
FLOW_DEBOUNCE_US = 1200

status_led = Pin(STATUS_LED_PIN, Pin.OUT)
sht_i2c = I2C(SHT_I2C_ID, sda=Pin(SHT_I2C_SDA_PIN), scl=Pin(SHT_I2C_SCL_PIN), freq=100000)
flow_pin = Pin(FLOW_PIN, Pin.IN, Pin.PULL_UP)
lighting_pin = Pin(LIGHTING_PIN, Pin.IN, Pin.PULL_UP)
cross_auger_pin = Pin(CROSS_AUGER_PIN, Pin.IN)
auger_left_pin = Pin(AUGER_LEFT_PIN, Pin.IN)
auger_right_pin = Pin(AUGER_RIGHT_PIN, Pin.IN)
hx711_dout = Pin(HX711_DOUT_PIN, Pin.IN, Pin.PULL_UP)
hx711_sck = Pin(HX711_SCK_PIN, Pin.OUT)
watchdog = WDT(timeout=WATCHDOG_TIMEOUT_MS)

flow_pulse_count = 0
total_flow_pulses = 0
last_flow_pulse_us = None
boot_ms = time.ticks_ms()
last_flow_calc_ms = time.ticks_ms()
last_temp_rh_ms = time.ticks_ms() - int(TEMP_RH_MEASURE_SECONDS * 1000)
last_temp_c = None
last_rh_pct = None


def next_boot_count():
    current = 0
    try:
        with open(BOOT_COUNT_FILE, "r") as handle:
            current = int((handle.read() or "0").strip() or "0")
    except Exception:
        current = 0

    current += 1
    try:
        with open(BOOT_COUNT_FILE, "w") as handle:
            handle.write(str(current))
    except Exception:
        pass
    return current


def current_reset_cause_label():
    try:
        cause = machine.reset_cause()
    except Exception:
        return "unknown"

    labels = {
        getattr(machine, "PWRON_RESET", object()): "power_on",
        getattr(machine, "HARD_RESET", object()): "hard_reset",
        getattr(machine, "WDT_RESET", object()): "watchdog_reset",
        getattr(machine, "DEEPSLEEP_RESET", object()): "deepsleep_reset",
        getattr(machine, "SOFT_RESET", object()): "soft_reset",
    }
    return labels.get(cause, str(cause))


BOOT_COUNT = next_boot_count()
RESET_CAUSE_LABEL = current_reset_cause_label()


def setup_inputs():
    hx711_sck.value(0)


def flow_pulse_handler(pin):
    global flow_pulse_count, total_flow_pulses, last_flow_pulse_us
    now_us = time.ticks_us()
    if last_flow_pulse_us is not None:
        if time.ticks_diff(now_us, last_flow_pulse_us) < FLOW_DEBOUNCE_US:
            return
    last_flow_pulse_us = now_us
    flow_pulse_count += 1
    total_flow_pulses += 1


def crc8(data_bytes):
    crc = 0xFF
    for byte in data_bytes:
        crc ^= byte
        bit = 0
        while bit < 8:
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
            bit += 1
    return crc


def read_sht45():
    sht_i2c.writeto(SHT45_ADDR, SHT45_MEASURE_HIGH_PRECISION)
    time.sleep_ms(10)
    raw = sht_i2c.readfrom(SHT45_ADDR, 6)

    temp_bytes = raw[0:2]
    temp_crc = raw[2]
    rh_bytes = raw[3:5]
    rh_crc = raw[5]

    if crc8(temp_bytes) != temp_crc:
        raise Exception("SHT45 temperature CRC failed")
    if crc8(rh_bytes) != rh_crc:
        raise Exception("SHT45 humidity CRC failed")

    raw_temp = (temp_bytes[0] << 8) | temp_bytes[1]
    raw_rh = (rh_bytes[0] << 8) | rh_bytes[1]

    temp_c = -45.0 + 175.0 * (raw_temp / 65535.0)
    rh_pct = -6.0 + 125.0 * (raw_rh / 65535.0)

    if rh_pct < 0:
        rh_pct = 0
    if rh_pct > 100:
        rh_pct = 100

    return round(temp_c, 1), round(rh_pct, 1)


def read_switch_active(pin):
    value = pin.value()
    if AUGER_INPUT_ACTIVE_LOW:
        return value == 0
    return value == 1


def update_temp_rh():
    global last_temp_c, last_rh_pct, last_temp_rh_ms

    now_ms = time.ticks_ms()
    if time.ticks_diff(now_ms, last_temp_rh_ms) < int(TEMP_RH_MEASURE_SECONDS * 1000):
        return

    last_temp_c, last_rh_pct = read_sht45()
    last_temp_rh_ms = now_ms


def read_temp_c():
    update_temp_rh()
    return last_temp_c


def read_rh_pct():
    update_temp_rh()
    return last_rh_pct


def read_water_lpm():
    global flow_pulse_count, last_flow_calc_ms

    now_ms = time.ticks_ms()
    elapsed_ms = time.ticks_diff(now_ms, last_flow_calc_ms)
    if elapsed_ms <= 0:
        return 0.0

    pulses = flow_pulse_count
    flow_pulse_count = 0
    last_flow_calc_ms = now_ms

    pulses_per_second = pulses / (elapsed_ms / 1000.0)
    lpm = pulses_per_second / FLOW_HZ_PER_LPM
    return round(lpm, 2)


def read_total_flow_pulses():
    return total_flow_pulses


def hx711_read_raw(timeout_ms=250):
    start_ms = time.ticks_ms()
    while hx711_dout.value() == 1:
        if time.ticks_diff(time.ticks_ms(), start_ms) > timeout_ms:
            raise Exception("HX711 not ready")
        time.sleep_ms(1)

    value = 0
    bit = 0
    while bit < 24:
        hx711_sck.value(1)
        value = (value << 1) | hx711_dout.value()
        hx711_sck.value(0)
        bit += 1

    # Gain/channel select: 25th pulse keeps channel A gain 128.
    hx711_sck.value(1)
    hx711_sck.value(0)

    if value & 0x800000:
        value -= 0x1000000
    return value


def read_feed_raw_units(samples=HX711_READINGS):
    readings = []
    idx = 0
    while idx < samples:
        readings.append(hx711_read_raw())
        idx += 1

    readings.sort()
    if len(readings) > 2:
        readings = readings[1:-1]
    return round(sum(readings) / len(readings), 1)


def read_value(read_fn, alarm_prefix, alarms, default=None):
    try:
        return read_fn()
    except Exception as exc:
        alarms.append("%s: %s" % (alarm_prefix, exc))
        return default


def read_auger_inputs(alarms):
    payload = {}
    input_map = {
        "lighting_on": lighting_pin,
        "cross_auger_on": cross_auger_pin,
        "auger_left_on": auger_left_pin,
        "auger_right_on": auger_right_pin,
    }

    for key, pin in input_map.items():
        try:
            payload[key] = read_switch_active(pin)
        except Exception as exc:
            payload[key] = None
            alarms.append("%s read failed: %s" % (key, exc))

    return payload


def base_payload(packet_kind="full", checkpoint=None):
    payload = {
        "device": DEVICE_NAME,
        "ts": time.time(),
        "uptime_s": int(time.ticks_diff(time.ticks_ms(), boot_ms) / 1000),
        "boot_count": BOOT_COUNT,
        "reset_cause": RESET_CAUSE_LABEL,
        "packet_kind": packet_kind,
    }
    if checkpoint:
        payload["checkpoint"] = checkpoint
    return payload


def emit_checkpoint(checkpoint):
    payload = base_payload(packet_kind="checkpoint", checkpoint=checkpoint)
    payload["status"] = "Checkpoint"
    payload["alarms"] = []
    print(json.dumps(payload))


def build_payload():
    alarms = []
    emit_checkpoint("pre_sht")
    temp_c = read_value(read_temp_c, "Temp read failed", alarms)
    rh_pct = read_value(read_rh_pct, "Humidity read failed", alarms)
    water_lpm = read_value(read_water_lpm, "Flow read failed", alarms)
    total_pulses = read_value(read_total_flow_pulses, "Total flow pulse read failed", alarms)
    emit_checkpoint("pre_hx711")
    feed_raw_units = read_value(read_feed_raw_units, "Feed raw read failed", alarms)
    emit_checkpoint("pre_augers")
    auger_payload = read_auger_inputs(alarms)

    payload = base_payload(packet_kind="full", checkpoint="full")
    payload.update({
        "temp_c": temp_c,
        "rh_pct": rh_pct,
        "water_lpm": water_lpm,
        "total_flow_pulses": total_pulses,
        "feed_raw_units": feed_raw_units,
        "feed_kg": None,
        "status": "Sensors OK" if not alarms else "Sensor warnings",
        "alarms": alarms,
    })

    for key in auger_payload:
        payload[key] = auger_payload[key]

    return payload


def main():
    setup_inputs()
    flow_pin.irq(trigger=Pin.IRQ_FALLING, handler=flow_pulse_handler)

    while True:
        try:
            watchdog.feed()
            status_led.toggle()
            print(json.dumps(build_payload()))
        except Exception as exc:
            watchdog.feed()
            payload = base_payload(packet_kind="error", checkpoint="exception")
            payload.update({
                "status": "Sensor read error",
                "alarms": [str(exc)],
            })
            print(json.dumps(payload))

        time.sleep(SAMPLE_SECONDS)


main()
