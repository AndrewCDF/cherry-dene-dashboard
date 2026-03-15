import json
import time

from machine import I2C, Pin


SAMPLE_SECONDS = 1.0
TEMP_RH_MEASURE_SECONDS = 2.5
DEVICE_NAME = "pico-2-shed"
DEBUG_ADS1115 = True

# Change these pin numbers to match your wiring.
SHT_I2C_ID = 0
SHT_I2C_SDA_PIN = 4
SHT_I2C_SCL_PIN = 5
ADS_I2C_ID = 1
ADS_I2C_SDA_PIN = 6
ADS_I2C_SCL_PIN = 7
SHT45_ADDR = 0x44
ADS1115_ADDR = 0x48
FLOW_PIN = 3
STATUS_LED_PIN = "LED"
HX711_DOUT_PIN = 14
HX711_SCK_PIN = 15
HX711_READINGS = 8

# SHT4x high precision measurement command.
SHT45_MEASURE_HIGH_PRECISION = b"\xFD"

# Hall-effect flow meter calibration.
# Example for common YF-S201-style meters:
#   L/min = pulses_per_second / 7.5
FLOW_HZ_PER_LPM = 7.5

# ADS1115 current transformer inputs.
# Assumed channel map:
#   A0 = cross auger
#   A1 = auger left
#   A2 = auger right
CT_CONFIG = {
    "cross_auger_on": {"channel": 0, "threshold": 2000},
    "auger_left_on": {"channel": 1, "threshold": 2000},
    "auger_right_on": {"channel": 2, "threshold": 2000},
}

ADS1115_REG_CONVERSION = 0x00
ADS1115_REG_CONFIG = 0x01
ADS1115_CONFIG_OS_SINGLE = 0x8000
ADS1115_CONFIG_MUX_BASE = 0x4000
ADS1115_CONFIG_PGA_4V096 = 0x0200
ADS1115_CONFIG_MODE_SINGLE = 0x0100
ADS1115_CONFIG_DR_860SPS = 0x00E0
ADS1115_CONFIG_COMP_DISABLE = 0x0003


status_led = Pin(STATUS_LED_PIN, Pin.OUT)
sht_i2c = I2C(SHT_I2C_ID, sda=Pin(SHT_I2C_SDA_PIN), scl=Pin(SHT_I2C_SCL_PIN), freq=100000)
ads_i2c = I2C(ADS_I2C_ID, sda=Pin(ADS_I2C_SDA_PIN), scl=Pin(ADS_I2C_SCL_PIN), freq=100000)
flow_pin = Pin(FLOW_PIN, Pin.IN, Pin.PULL_UP)
hx711_dout = Pin(HX711_DOUT_PIN, Pin.IN, Pin.PULL_UP)
hx711_sck = Pin(HX711_SCK_PIN, Pin.OUT)

flow_pulse_count = 0
total_flow_pulses = 0
boot_ms = time.ticks_ms()
last_flow_calc_ms = time.ticks_ms()
last_temp_rh_ms = time.ticks_ms() - int(TEMP_RH_MEASURE_SECONDS * 1000)
last_temp_c = None
last_rh_pct = None


def setup_inputs():
    hx711_sck.value(0)


def ads1115_write_config(config_value):
    payload = bytes([
        ADS1115_REG_CONFIG,
        (config_value >> 8) & 0xFF,
        config_value & 0xFF,
    ])
    ads_i2c.writeto(ADS1115_ADDR, payload)


def ads1115_read_conversion():
    ads_i2c.writeto(ADS1115_ADDR, bytes([ADS1115_REG_CONVERSION]))
    raw = ads_i2c.readfrom(ADS1115_ADDR, 2)
    value = (raw[0] << 8) | raw[1]
    if value & 0x8000:
        value -= 0x10000
    return value


def ads1115_read_channel(channel):
    if channel < 0 or channel > 3:
        raise ValueError("ADS1115 channel must be 0-3")

    mux_bits = ADS1115_CONFIG_MUX_BASE + (channel << 12)
    config = (
        ADS1115_CONFIG_OS_SINGLE
        | mux_bits
        | ADS1115_CONFIG_PGA_4V096
        | ADS1115_CONFIG_MODE_SINGLE
        | ADS1115_CONFIG_DR_860SPS
        | ADS1115_CONFIG_COMP_DISABLE
    )
    ads1115_write_config(config)
    time.sleep_ms(2)
    return ads1115_read_conversion()


def flow_pulse_handler(pin):
    global flow_pulse_count, total_flow_pulses
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


def read_ct_active(channel, threshold, samples=12):
    peak = 0
    i = 0
    while i < samples:
        val = abs(ads1115_read_channel(channel))
        if val > peak:
            peak = val
        i += 1
    return peak >= int(threshold), peak


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


def read_light_lux():
    return None


def read_pressure_pa():
    return None


def read_value(read_fn, alarm_prefix, alarms, default=None):
    try:
        return read_fn()
    except Exception as exc:
        alarms.append("%s: %s" % (alarm_prefix, exc))
        return default


def read_ct_block(alarms):
    ct_payload = {}
    ct_debug = {}

    for key in CT_CONFIG:
        channel = CT_CONFIG[key]["channel"]
        threshold = CT_CONFIG[key]["threshold"]
        try:
            active, peak = read_ct_active(channel, threshold)
            ct_payload[key] = active
            ct_payload[key + "_peak"] = peak
            if DEBUG_ADS1115:
                ct_debug[key] = {
                    "channel": channel,
                    "peak": peak,
                    "threshold": int(threshold),
                }
        except Exception as exc:
            ct_payload[key] = None
            ct_payload[key + "_peak"] = None
            alarms.append("%s CT read failed: %s" % (key, exc))
            if DEBUG_ADS1115:
                ct_debug[key] = {
                    "channel": channel,
                    "peak": None,
                    "threshold": int(threshold),
                    "error": str(exc),
                }

    return ct_payload, ct_debug


def build_payload():
    alarms = []
    ts = time.time()
    uptime_s = int(time.ticks_diff(time.ticks_ms(), boot_ms) / 1000)

    temp_c = read_value(read_temp_c, "Temp read failed", alarms)
    rh_pct = read_value(read_rh_pct, "Humidity read failed", alarms)
    water_lpm = read_value(read_water_lpm, "Flow read failed", alarms)
    total_pulses = read_value(read_total_flow_pulses, "Total flow pulse read failed", alarms)
    feed_raw_units = read_value(read_feed_raw_units, "Feed raw read failed", alarms)
    light_lux = read_value(read_light_lux, "Light read failed", alarms)
    pressure_pa = read_value(read_pressure_pa, "Pressure read failed", alarms)
    ct_payload, ct_debug = read_ct_block(alarms)

    payload = {
        "device": DEVICE_NAME,
        "ts": ts,
        "uptime_s": uptime_s,
        "temp_c": temp_c,
        "rh_pct": rh_pct,
        "water_lpm": water_lpm,
        "total_flow_pulses": total_pulses,
        "feed_raw_units": feed_raw_units,
        "feed_kg": None,
        "light_lux": light_lux,
        "pressure_pa": pressure_pa,
        "status": "Sensors OK" if not alarms else "Sensor warnings",
        "alarms": alarms,
    }

    for key in ct_payload:
        payload[key] = ct_payload[key]

    if DEBUG_ADS1115:
        payload["ct_debug"] = ct_debug

    return payload


def main():
    setup_inputs()
    flow_pin.irq(trigger=Pin.IRQ_FALLING, handler=flow_pulse_handler)

    while True:
        try:
            status_led.toggle()
            print(json.dumps(build_payload()))
        except Exception as exc:
            print(json.dumps({
                "status": "Sensor read error",
                "alarms": [str(exc)],
            }))

        time.sleep(SAMPLE_SECONDS)


main()
