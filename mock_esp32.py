"""mock_esp32.py — Giả lập ESP32-S3 gửi/nhận MQTT."""
import json
import random
import time
import threading

import paho.mqtt.client as mqtt


DEVICE_ID = "mock-esp32-001"
BROKER = "localhost"
PORT = 1883
TOPIC_UP = f"xiaozhi/{DEVICE_ID}/up"
TOPIC_DOWN = f"xiaozhi/{DEVICE_ID}/down"


class MockESP32:
    def __init__(self):
        self.client = mqtt.Client(client_id=DEVICE_ID)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        self.lamp_on = False
        self.brightness = 50
        self.color_temp = 50

        self.sensors = {
            "temperature": 28.5,
            "humidity": 65.0,
            "air_quality_ppm": 750,
            "light_lux": 350,
            "presence": True,
        }

    def _on_connect(self, client, userdata, flags, rc, *args):
        print(f"✅ MQTT connected (rc={rc})")
        client.subscribe(TOPIC_DOWN)
        print(f"📡 Subscribed: {TOPIC_DOWN}")
        self._send_hello()

    def _on_message(self, client, userdata, msg, *args):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
            print(f"\n📨 ← {data}")
            self._handle(data)
        except Exception as e:
            print(f"❌ Parse lỗi: {e}")

    def _handle(self, data):
        msg_type = data.get("type")

        if msg_type == "hello":
            print(f"🔑 Session: {data.get('session_id')}")
            udp = data.get("udp", {})
            print(f"🔑 UDP: {udp.get('server')}:{udp.get('port')}")
            return

        if msg_type == "mcp":
            payload = data.get("payload") or {}
            call = payload.get("params") or {}
            method = call.get("name") or data.get("method")
            params = call.get("arguments") or data.get("params") or {}
            print(f"🎛️  MCP: {method}({params})")

            if method == "Lamp.TurnOn":
                self.lamp_on = True
                print(f"   💡 Đèn BẬT (brightness={self.brightness}%)")
                self._send_lamp_status()

            elif method == "Lamp.TurnOff":
                self.lamp_on = False
                print(f"   💡 Đèn TẮT")
                self._send_lamp_status()

            elif method == "Lamp.SetBrightness":
                self.brightness = params.get("value", 50)
                self.lamp_on = self.brightness > 0
                print(f"   💡 Độ sáng = {self.brightness}%")
                self._send_lamp_status()

            elif method == "Lamp.SetColorTemp":
                self.color_temp = params.get("value", 50)
                temp_name = (
                    "vàng ấm" if self.color_temp < 35
                    else "trắng lạnh" if self.color_temp > 65
                    else "trung tính"
                )
                print(f"   🎨 Màu = {self.color_temp} ({temp_name})")
                self._send_lamp_status()

            elif method == "Sensor.Read":
                sensor = params.get("sensor", "all")
                print(f"   📊 Đọc {sensor} = {self._get_sensor(sensor)}")
                self._send_sensor_data(sensor)

            else:
                print(f"   ⚠️  Không biết method: {method}")

    def _get_sensor(self, name):
        if name == "all":
            return self.sensors
        return self.sensors.get(name)

    def _send_hello(self):
        hello = {
            "type": "hello",
            "version": 3,
            "transport": "mqtt",
            "device_id": DEVICE_ID,
            "features": {"mcp": True},
        }
        self.client.publish(TOPIC_UP, json.dumps(hello))
        print(f"📤 Hello: {hello}")

    def _send_lamp_status(self):
        payload = {
            "type": "mcp_reply",
            "method": "Lamp.Status",
            "result": {
                "on": self.lamp_on,
                "brightness": self.brightness,
                "color_temp": self.color_temp,
            },
        }
        self.client.publish(TOPIC_UP, json.dumps(payload))

    def _send_sensor_data(self, sensor="all"):
        if sensor == "all":
            data = self.sensors.copy()
        else:
            data = {sensor: self.sensors.get(sensor)}
        payload = {"type": "sensor_data", "device_id": DEVICE_ID, **data}
        self.client.publish(TOPIC_UP, json.dumps(payload))

    def _update_sensors(self):
        while True:
            time.sleep(10)
            self.sensors["temperature"] = round(24 + random.uniform(0, 8), 1)
            self.sensors["humidity"] = round(50 + random.uniform(0, 30), 0)
            self.sensors["air_quality_ppm"] = random.randint(400, 1500)
            self.sensors["light_lux"] = random.randint(100, 800)
            self.sensors["presence"] = random.choice([True, False])
            print(f"\n📊 Update sensors: {self.sensors}")
            self._send_sensor_data("all")

    def run(self):
        self.client.connect(BROKER, PORT, 60)
        self.client.loop_start()
        threading.Thread(target=self._update_sensors, daemon=True).start()

        print(f"\n{'=' * 50}")
        print(f"  🤖 MOCK ESP32-S3: {DEVICE_ID}")
        print(f"{'=' * 50}")
        print(f"Đang lắng nghe lệnh từ server...")
        print(f"Ctrl+C để dừng\n")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n👋 Dừng mock")
            self.client.loop_stop()
            self.client.disconnect()


if __name__ == "__main__":
    MockESP32().run()
