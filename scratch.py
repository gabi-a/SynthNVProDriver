import time

from nvprocontroller import SynthNVProController
from serialconnection import SerialConnection

ser = SerialConnection('COM4', 2000000)
nv = SynthNVProController(ser)


responses = nv.get_help()
for line in responses:
    print(line)


freq = nv.get_rf_frequency()
print(f"Frequency: {freq} MHz")

time.sleep(0.01)

nv.set_rf_power(-20)
power = nv.get_rf_power()
print(f"Power: {power} dBm")

readings = nv.read_power_detector(10)
print(readings)

nv.set_pll_enable(True)

time.sleep(1)

readings = nv.read_power_detector(10)
print(readings)

nv.set_pll_enable(False)