"""Background maintenance and polling tasks."""
import asyncio
from loguru import logger

from app.core.device_hub import get_device_hub, parse_mcp_result
from app.database import AsyncSessionLocal
from app.repositories import chat as chat_repo


async def cleanup_stale_sessions_loop(interval_sec: int = 600, max_idle_hours: int = 1):
    """Định kỳ đóng các session cũ không còn hoạt động."""
    while True:
        try:
            await asyncio.sleep(interval_sec)
            async with AsyncSessionLocal() as db:
                n = await chat_repo.cleanup_stale_sessions(db, max_idle_hours=max_idle_hours)
                if n:
                    logger.info(f"🧹 Closed {n} stale sessions")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"cleanup stale sessions: {e}")


async def poll_sensors_loop(interval_sec: int = 10):
    """Poll cảm biến từ **từng** ESP32 rồi đẩy đúng UI của thiết bị đó."""
    from app.core.providers.tools.builtin import _send_mcp_command
    from app.core.providers.tools.device_mcp_manager import get_device_mcp_manager
    from app.core.mqtt_server import get_mqtt_manager

    hub = get_device_hub()

    while True:
        try:
            await asyncio.sleep(interval_sec)
            # Gồm cả device WS lẫn MQTT — trước đây chỉ lấy device đầu tiên.
            mqtt_manager = get_mqtt_manager()
            now = asyncio.get_running_loop().time()
            mqtt_control = {
                device_id for device_id, state in mqtt_manager.control_devices.items()
                if now - state.get("last_seen", 0) <= 90.0
            }
            devices = (
                set(hub.all_esp32())
                | set(get_device_mcp_manager()._transports)
                | set(mqtt_manager.sessions)
                | mqtt_control
            )
            for device_id in devices:
                try:
                    result = await _send_mcp_command(
                        "self.get_environment", {}, timeout=5.0, device_id=device_id
                    )
                    data = parse_mcp_result(result)
                    if not data:
                        continue

                    hub.update_sensors(data, device_id=device_id)
                    await hub.broadcast_sync(device_id, "sensor_update", data)

                    for _web_id, chat_ws in hub.get_chats_by_device(device_id):
                        try:
                            await chat_ws.send_json({
                                "type": "sensor_update",
                                "data": data,
                                **data,
                            })
                        except Exception:
                            pass
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.debug(f"Poll sensor {device_id}: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Poll sensor error: {e}")