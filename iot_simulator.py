"""
GeoEther IoT telemetry simulator
Sends simulated temperature, humidity, and air-quality readings to Azure IoT Hub.

Install:
    python -m pip install azure-iot-device

Run:
    python iot_simulator.py

When prompted, paste the DEVICE connection string from:
Azure Portal -> IoT Hub -> Devices -> your device -> Primary connection string.
The connection string is entered privately and is not saved to this file.
Press Ctrl+C to stop.
"""

import json
import random
import time
from datetime import datetime, timezone
from getpass import getpass

from azure.iot.device import IoTHubDeviceClient, Message

SEND_INTERVAL_SECONDS = 5


def main():
    print("GeoEther IoT telemetry simulator")
    print("Paste your IoT DEVICE connection string when prompted.")
    print("It will not be displayed or saved in this script.\n")

    connection_string = getpass("Device connection string: ").strip()
    if not connection_string:
        print("No connection string entered. Exiting.")
        return

    device_id = "geoether-device"
    for part in connection_string.split(";"):
        if part.strip().lower().startswith("deviceid="):
            device_id = part.split("=", 1)[1].strip()
            break

    client = None
    try:
        client = IoTHubDeviceClient.create_from_connection_string(connection_string)
        print("\nConnecting to Azure IoT Hub...")
        client.connect()
        print(f"Connected. Sending telemetry every {SEND_INTERVAL_SECONDS} seconds.")
        print("Press Ctrl+C to stop.\n")

        while True:
            payload = {
                "device_id": device_id,
                "temperature": round(random.uniform(22.0, 35.0), 1),
                "humidity": round(random.uniform(35.0, 85.0), 1),
                "air_quality": random.randint(10, 150),
                "event_time": datetime.now(timezone.utc).isoformat(),
            }

            message = Message(json.dumps(payload))
            message.content_encoding = "utf-8"
            message.content_type = "application/json"

            try:
                client.send_message(message)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent: {json.dumps(payload)}")
            except Exception as exc:
                print(f"Send failed: {type(exc).__name__}: {exc}")
                print("Check the device connection string and IoT Hub connectivity.")

            time.sleep(SEND_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopping simulator...")
    except Exception as exc:
        print(f"\nSimulator error: {type(exc).__name__}: {exc}")
        print("Confirm you used the DEVICE connection string (not the IoT Hub owner/service connection string).")
    finally:
        if client is not None:
            try:
                client.shutdown()
            except Exception:
                pass
        print("Simulator stopped.")


if __name__ == "__main__":
    main()
