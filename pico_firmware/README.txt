Pico 2 firmware for the shed controller

Files:
- main.py

Current hardware this starter now targets:
- Sensirion SHT45 temp / humidity sensor over I2C
- 3-wire hall-effect pulse flow meter
- 4 shear beam load cells into a 4-in-1 junction box, then HX711, then Pico
- current transformers through an ADS1115 for:
  - cross_auger_on
  - auger_left_on
  - auger_right_on

Current assumptions:
- SHT45 is on I2C bus 0
- SHT45 SDA is GPIO 4
- SHT45 SCL is GPIO 5
- ADS1115 is on I2C bus 1
- ADS1115 SDA is GPIO 6
- ADS1115 SCL is GPIO 7
- SHT45 address is 0x44
- ADS1115 address is 0x48
- ADS1115 channel map is:
  - A0 = cross auger
  - A1 = auger left
  - A2 = auger right
- flow meter pulse wire is on GPIO 3
- HX711 DOUT is on GPIO 14
- HX711 SCK is on GPIO 15
- the flow meter uses:
  L/min = pulses_per_second / 7.5
  which is common for YF-S201-style meters

What the firmware sends over USB serial:
- device
- ts
- uptime_s
- temp_c
- rh_pct
- water_lpm
- total_flow_pulses
- feed_raw_units
- feed_kg
- light_lux
- pressure_pa
- cross_auger_on
- auger_left_on
- auger_right_on
- cross_auger_on_peak
- auger_left_on_peak
- auger_right_on_peak
- status
- alarms
- ct_debug

What you need to edit:
1. Change SHT_I2C_ID, SHT_I2C_SDA_PIN, and SHT_I2C_SCL_PIN if your SHT45 is wired differently.
2. Change ADS_I2C_ID, ADS_I2C_SDA_PIN, and ADS_I2C_SCL_PIN if your ADS1115 is wired differently.
3. Change SHT45_ADDR if your board uses the alternate SHT4x address.
4. Change FLOW_PIN if your hall-effect flow meter pulse wire is on another GPIO.
5. Change FLOW_HZ_PER_LPM to match your actual flow meter calibration.
6. Change HX711_DOUT_PIN and HX711_SCK_PIN if your HX711 is wired differently.
7. Change the ADS1115 CT channels and thresholds if your auger wiring differs.
8. Replace the placeholder functions if you later add:
   - light sensor
   - pressure sensor
9. Set `DEVICE_NAME` so the shed Pi can identify the Pico cleanly.
10. Set `DEBUG_ADS1115 = False` later if you do not want CT debug data in the JSON output.

Wiring notes:
- SHT45:
  - VCC to 3.3V
  - GND to GND
  - SDA to GPIO set by SHT_I2C_SDA_PIN
  - SCL to GPIO set by SHT_I2C_SCL_PIN

- 3-wire hall flow meter:
  - red to supply
  - black to GND
  - signal to GPIO set by FLOW_PIN
  - this starter uses Pin.PULL_UP and counts falling edges

- feed bin weigh cells:
  - 4 load cells into the 4-in-1 junction box
  - junction box signal output into HX711 input
  - HX711 VCC to Pico 3.3V or board-required supply
  - HX711 GND to Pico GND
  - HX711 DOUT to GPIO set by HX711_DOUT_PIN
  - HX711 SCK to GPIO set by HX711_SCK_PIN
  - firmware sends raw averaged counts as `feed_raw_units`
  - the shed controller uses that raw value for tare, known-weight calibration, and live KG

- auger current transformers:
  - CT outputs go into the ADS1115 analog inputs
  - ADS1115 uses its own Pico I2C bus
  - default firmware assumption is bus 1 on GPIO 6/7
  - default ADS1115 address is `0x48`
  - firmware reads:
    - `A0` for `cross_auger_on`
    - `A1` for `auger_left_on`
    - `A2` for `auger_right_on`

Deployment:
1. Flash MicroPython to the Pico 2.
2. Copy main.py to the Pico as /main.py.
3. Plug the Pico 2 into the shed Pi 5 by USB.
4. The shed controller reads the JSON lines from /dev/ttyACM0 or similar.

Important:
- this starter includes a minimal built-in SHT45 read path, so it does not rely on an extra driver file
- if your flow meter calibration is different, the displayed L/min will be wrong until FLOW_HZ_PER_LPM is adjusted
- the shed controller can now use `total_flow_pulses` for a 5 minute calibration against the physical water meter
- the shed controller feed settings page expects `feed_raw_units`, not pre-calculated feed KG
- the auger threshold values in `main.py` are starting values and will likely need tuning from live ADS1115 readings
- each sensor path now fails independently, so a feed or CT issue should not stop temp, humidity, or flow data being sent
- `ct_debug` includes the live ADS1115 channel, peak, and threshold for each auger input, which is useful while tuning thresholds
