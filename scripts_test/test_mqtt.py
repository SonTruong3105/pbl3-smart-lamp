"""Test MQTT — dùng paho-mqtt synchronous (không cần asyncio)."""
import json
import sys
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("❌ Cần cài paho-mqtt: pip install paho-mqtt")
    sys.exit(1)


def test():
    received = []

    def on_connect(client, userdata, flags, rc, *args):
        print(f"✅ Connected (rc={rc})")
        client.subscribe("xiaozhi/test/down")
        print("✅ Subscribed: xiaozhi/test/down")

        hello = {"type": "hello", "version": 3, "transport": "udp"}
        client.publish("xiaozhi/test/up", json.dumps(hello))
        print("✅ Sent hello")

    def on_message(client, userdata, msg, *args):
        payload = msg.payload.decode("utf-8")
        print(f"← {payload}")
        received.append(payload)
        client.disconnect()

    # Compat paho-mqtt 1.x và 2.x
    try:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id="test-client",
        )
    except AttributeError:
        client = mqtt.Client(client_id="test-client")

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect("localhost", 1883, 60)
    except Exception as e:
        print(f"❌ Không kết nối broker: {e}")
        return

    client.loop_start()
    time.sleep(10)
    client.loop_stop()

    if received:
        print(f"\n✅ Nhận {len(received)} message(s)")
    else:
        print("\n❌ Timeout — backend không reply")


if __name__ == "__main__":
    test()