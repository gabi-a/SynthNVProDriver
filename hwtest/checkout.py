"""Hardware checkout for a connected SynthNV Pro (use with a spectrum analyser
or power meter on RFout; leave RFin unconnected or attenuated).

Usage: uv run python hwtest/checkout.py [--port PORT] [--power DBM]

It never goes above --power (default -30 dBm) and powers the RF down at the end.
"""

import argparse
import logging

from SynthNVProDriver import SynthNVPro, find_ports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port")
    parser.add_argument("--power", type=float, default=-30.0, help="RF power cap and test level, dBm")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    print("SynthNV Pro ports found:", find_ports() if args.port is None else [args.port])
    with SynthNVPro.connect(args.port, max_power_dbm=args.power) as synth:
        print(synth.info())
        synth.set_frequency(1000.0)
        synth.set_power(args.power)
        print("status before enable:", synth.status())
        synth.enable()
        print("status enabled:", synth.status())
        input("RF is on at 1000 MHz: check the analyser, then press Enter...")

        synth.sweep.configure(900.0, 1100.0, step_mhz=10.0, step_time_ms=100.0,
                              power_dbm=args.power)
        synth.sweep.start()
        input("Sweeping 900-1100 MHz: check the analyser, then press Enter...")
        synth.sweep.stop()

        print("RFin power:", synth.detector.read(3), "dBm")
        print("temperature:", synth.get_temperature(), "C")
    print("RF output powered down.")


if __name__ == "__main__":
    main()
