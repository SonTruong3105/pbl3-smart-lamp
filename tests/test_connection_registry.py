import inspect
from app.core import connection_registry, sync


def test_connection_registry_sync_bridge():
    device_id = "test-device-999"
    fake = {"name": "test_esp32"}
    sync.register_esp32(device_id, fake)
    assert connection_registry.get(device_id) is fake

    coro = connection_registry.all_active()
    assert inspect.iscoroutine(coro)
    try:
        coro.send(None)
    except StopIteration as e:
        items = e.value
        assert (device_id, fake) in items

    sync.unregister_esp32(device_id)
    assert connection_registry.get(device_id) is None
