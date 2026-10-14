"""
GeoEther IoT telemetry simulator (Multi-Device Version)
Sends simulated temperature, humidity, and air-quality readings from 
multiple devices to Azure IoT Hub concurrently.

Install:
    python -m pip install azure-iot-device

Run:
    python iot_simulator.py
"""

import json
import random
import threading
import time
from datetime import datetime, timezone
from getpass import getpass

from azure.iot.device import IoTHubDeviceClient, Message

SEND_INTERVAL_SECONDS = 5
NUM_DEVICES = 4


def simulate_device(device_index, connection_string):
    """Worker function to run telemetry simulation for a single device connection string."""
    device_id = f"device-{device_index}"
    for part in connection_string.split(";"):
        if part.strip().lower().startswith("deviceid="):
            device_id = part.split("=", 1)[1].strip()
            break

    client = None
    try:
        client = IoTHubDeviceClient.create_from_connection_string(connection_string)
        client.connect()
        print(f"[{device_id}] Connected and sending telemetry every {SEND_INTERVAL_SECONDS}s.")

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
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [{device_id}] Sent: {json.dumps(payload)}")
            except Exception as exc:
                print(f"[{device_id}] Send failed: {type(exc).__name__}: {exc}")

            time.sleep(SEND_INTERVAL_SECONDS)

    except Exception as exc:
        print(f"[{device_id}] Simulator error: {type(exc).__name__}: {exc}")
    finally:
        if client is not None:
            try:
                client.shutdown()
            except Exception:
                pass
        print(f"[{device_id}] Stopped.")


def main():
    print("GeoEther IoT Multi-Device Telemetry Simulator")
    print(f"You will be prompted to enter connection strings for {NUM_DEVICES} separate devices.\n")

    connection_strings = []
    for i in range(1, NUM_DEVICES + 1):
        conn_str = getpass(f"Device {i} connection string: ").strip()
        if not conn_str:
            print("Empty connection string entered. Stopping setup.")
            return
        connection_strings.append(conn_str)

    print(f"\nStarting {NUM_DEVICES} device threads. Press Ctrl+C to stop.\n")

    threads = []
    for idx, conn_str in enumerate(connection_strings, start=1):
        t = threading.Thread(target=simulate_device, args=(idx, conn_str), daemon=True)
        t.start()
        threads.append(t)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping all simulators...")


if __name__ == "__main__":
    main()