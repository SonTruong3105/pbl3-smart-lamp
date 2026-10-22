import re
from pathlib import Path

file = Path("core/api/ota_handler.py")
content = file.read_text(encoding="utf-8")

# Tìm và thay block mqtt
pattern = r'''    # ✅ MQTT section nếu enabled
    if config\.mqtt_enabled:
        response\["mqtt"\] = \{
            "enable": True,
            "endpoint": f"\{config\.mqtt_endpoint\}:\{config\.mqtt_broker_port\}",
        \}
        # Thêm thông tin UDP vào audio_params
        response\["audio_params"\]\["udp"\] = \{
            "server": config\.udp_endpoint,
            "port": config\.udp_port,
            "key": "",
            "nonce": "",
        \}
        logger\.info\(f"   → MQTT: \{config\.mqtt_endpoint\}:\{config\.mqtt_broker_port\}"\)
        logger\.info\(f"   → UDP:  \{config\.udp_endpoint\}:\{config\.udp_port\}"\)
    else:
        logger\.info\(f"   → WS: \{ws_url\}"\)'''

replacement = '''    # ✅ MQTT section nếu enabled
    if config.mqtt_enabled:
        mac = body.get("mac_address", "esp32-unknown")
        mqtt_endpoint_with_port = f"{config.mqtt_endpoint}:{config.mqtt_broker_port}"
        response["mqtt"] = {
            "enable": True,
            "endpoint": mqtt_endpoint_with_port,
            "client_id": mac,
            "username": mac,
            "password": "",
            "publish_topic": f"xiaozhi/{mac}/up",
        }
        logger.info(f"   → MQTT: {mqtt_endpoint_with_port}")
        logger.info(f"   → client_id: {mac}")
        logger.info(f"   → publish_topic: xiaozhi/{mac}/up")
        logger.info(f"   → UDP:  {config.udp_endpoint}:{config.udp_port}")
    else:
        logger.info(f"   → WS: {ws_url}")'''

new_content, count = re.subn(pattern, replacement, content)
if count > 0:
    file.write_text(new_content, encoding="utf-8")
    print(f"✅ Đã sửa {count} block")
else:
    print("⚠️ Không match — sửa thủ công")
    print("\nCần thay block MQTT bằng:")
    print(replacement)
