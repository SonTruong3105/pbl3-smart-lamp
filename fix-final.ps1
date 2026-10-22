# ============================================================
#  FIX FULL — VieNeu lock hang + 5 bugs
#  Chạy: cd D:\my-xiaozhi; .\fix-final.ps1
# ============================================================
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ✅ Absolute path from script location
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
Write-Host "📁 Root: $root" -ForegroundColor Cyan

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$bk = Join-Path $root "_backup_final_$stamp"
New-Item -ItemType Directory -Path $bk -Force | Out-Null
Write-Host "📦 Backup -> $bk" -ForegroundColor Cyan

function Backup($rel) {
    $src = Join-Path $root $rel
    if (Test-Path $src) {
        $leaf = Split-Path $rel -Leaf
        Copy-Item $src (Join-Path $bk $leaf) -Force
    }
}

function Read-Utf8($rel) {
    $path = Join-Path $root $rel
    if (-not (Test-Path $path)) {
        throw "Không tìm thấy: $path"
    }
    return [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
}

function Write-Utf8($rel, $content) {
    $path = Join-Path $root $rel
    $utf8 = New-Object System.Text.UTF8Encoding($false)   # ✅ No BOM
    [System.IO.File]::WriteAllText($path, $content, $utf8)
}

# ============================================================
# FIX 1 — vieneu.py
# ============================================================
Write-Host ""
Write-Host "[1/7] vieneu.py" -ForegroundColor Cyan
Backup "app\core\providers\tts\vieneu.py"

$vieneu = @'
"""VieNeu-TTS provider — async httpx thuần (không thread/subprocess)."""
import asyncio
import time
import httpx

from app.core.providers.base import TTSProviderBase, ProviderRegistry
from app.core.providers.tts.edge import clean_for_tts


_vieneu_lock = asyncio.Lock()
_consecutive_timeouts = 0
_LOCK_WAIT_TIMEOUT = 20.0


class VieNeuTTSProvider(TTSProviderBase):
    async def synthesize(self, text: str, **kwargs) -> bytes:
        global _consecutive_timeouts

        if not text.strip():
            return b""
        clean = clean_for_tts(text)
        if not clean:
            return b""

        url = self.config.get("url", "http://localhost:11436")
        voice = kwargs.get("voice") or self.config.get("voice", "Trúc Ly")
        timeout = min(float(self.config.get("request_timeout", 15.0)), 12.0)

        try:
            await asyncio.wait_for(
                _vieneu_lock.acquire(),
                timeout=_LOCK_WAIT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            self.log.error(f"🚨 Không giành được VieNeu lock sau {_LOCK_WAIT_TIMEOUT}s")
            return b""

        t_start = time.perf_counter()
        try:
            self.log.debug(f"🔒 VieNeu lock: {clean[:40]!r}")

            cfg = httpx.Timeout(connect=3.0, read=timeout, write=3.0, pool=3.0)
            async with httpx.AsyncClient(
                timeout=cfg,
                limits=httpx.Limits(max_keepalive_connections=0),
            ) as client:
                r = await client.post(
                    f"{url}/tts",
                    json={"text": clean, "voice": voice},
                    headers={"Connection": "close"},
                )
                r.raise_for_status()
                wav_bytes = r.content

            elapsed = (time.perf_counter() - t_start) * 1000
            _consecutive_timeouts = 0
            self.log.info(
                f"🔊 VieNeu [{elapsed:.0f}ms] voice={voice!r}: "
                f"{len(wav_bytes)}b | {clean[:40]!r}"
            )
            return wav_bytes

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            _consecutive_timeouts += 1
            elapsed = (time.perf_counter() - t_start) * 1000
            self.log.warning(
                f"⚠️ VieNeu timeout/connect sau {elapsed:.0f}ms: "
                f"{type(e).__name__} (#{_consecutive_timeouts})"
            )
            if _consecutive_timeouts >= 3:
                self.log.error("🚨 VieNeu treo 3 lần — restart server!")
            return b""
        except httpx.HTTPStatusError as e:
            self.log.error(f"❌ VieNeu HTTP {e.response.status_code}")
            return b""
        except asyncio.CancelledError:
            self.log.warning("⏹️ VieNeu request bị cancel")
            raise
        except Exception as e:
            self.log.error(f"❌ VieNeu lỗi: {type(e).__name__}: {e}")
            return b""
        finally:
            elapsed = (time.perf_counter() - t_start) * 1000
            self.log.debug(f"🔓 VieNeu release sau {elapsed:.0f}ms")
            try:
                _vieneu_lock.release()
            except RuntimeError:
                pass


ProviderRegistry.register_tts("vieneu", VieNeuTTSProvider)
'@

Write-Utf8 "app\core\providers\tts\vieneu.py" $vieneu
Write-Host "   ✅ done" -ForegroundColor Green

# ============================================================
# FIX 2+3+4 — connection.py
# ============================================================
Write-Host ""
Write-Host "[2-4/7] connection.py" -ForegroundColor Cyan
Backup "app\core\connection.py"

$conn = Read-Utf8 "app\core\connection.py"
$orig = $conn

# ----- 2: reorderer push + skip -----
$oldPush = @'
    async def push(self, idx: int, sentence: str, audio: bytes):
        async with self._lock:
            self._buf[idx] = (sentence, audio)
            while self._next_idx in self._buf:
                sent, data = self._buf.pop(self._next_idx)
                try:
                    await self._send({
                        "type": "audio",
                        "index": self._next_idx,
                        "total": self.total_ref["n"],
                        "sentence": sent,
                        "data": data,
                    })
                except Exception as e:
                    self._log.warning(f"⚠️ Reorderer #{self._next_idx}: {e}")
                self._next_idx += 1
'@

$newPush = @'
    async def _send_audio(self, i: int, sent: str, data: bytes):
        try:
            await asyncio.wait_for(
                self._send({
                    "type": "audio",
                    "index": i,
                    "total": self.total_ref["n"],
                    "sentence": sent,
                    "data": data,
                }),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            self._log.warning(f"⏰ Reorderer #{i} send timeout")
        except Exception as e:
            self._log.warning(f"⚠️ Reorderer #{i}: {e}")

    async def push(self, idx: int, sentence: str, audio: bytes):
        to_send = []
        async with self._lock:
            self._buf[idx] = (sentence, audio)
            while self._next_idx in self._buf:
                item = self._buf.pop(self._next_idx)
                if item is not None:
                    sent, data = item
                    to_send.append((self._next_idx, sent, data))
                self._next_idx += 1
        for i, sent, data in to_send:
            await self._send_audio(i, sent, data)

    async def skip(self, idx: int):
        to_send = []
        async with self._lock:
            self._buf[idx] = None
            while self._next_idx in self._buf:
                item = self._buf.pop(self._next_idx)
                if item is not None:
                    sent, data = item
                    to_send.append((self._next_idx, sent, data))
                self._next_idx += 1
        for i, sent, data in to_send:
            await self._send_audio(i, sent, data)
'@

if ($conn.Contains($oldPush)) {
    $conn = $conn.Replace($oldPush, $newPush)
    Write-Host "   ✅ reorderer push + skip" -ForegroundColor Green
} else {
    Write-Host "   ⚠️ Không match push" -ForegroundColor Yellow
}

# ----- 3: tts_consumer skip -----
$oldConsumer = @'
                    if audio:
                        await reorderer.push(idx, sentence, audio)
                        self.log.info(
                            f"🔊 W{worker_id} câu #{idx} "
                            f"({len(audio)}b, TTS={elapsed:.0f}ms)"
                        )
                except asyncio.TimeoutError:
                    self.log.warning(f"⏰ TTS câu #{idx} timeout")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.log.error(f"❌ TTS câu #{idx} lỗi: {e}")
'@

$newConsumer = @'
                    if audio:
                        await reorderer.push(idx, sentence, audio)
                        self.log.info(
                            f"🔊 W{worker_id} câu #{idx} "
                            f"({len(audio)}b, TTS={elapsed:.0f}ms)"
                        )
                    else:
                        self.log.warning(f"⚠️ W{worker_id} câu #{idx} rỗng → skip")
                        await reorderer.skip(idx)
                except asyncio.TimeoutError:
                    self.log.warning(f"⏰ TTS câu #{idx} timeout → skip")
                    await reorderer.skip(idx)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.log.error(f"❌ TTS câu #{idx} lỗi: {e} → skip")
                    await reorderer.skip(idx)
'@

if ($conn.Contains($oldConsumer)) {
    $conn = $conn.Replace($oldConsumer, $newConsumer)
    Write-Host "   ✅ tts_consumer skip" -ForegroundColor Green
} else {
    Write-Host "   ⚠️ Không match consumer" -ForegroundColor Yellow
}

# ----- 4: abort async -----
$oldAbort = @'
    def abort(self):
        if self._pipeline_task and not self._pipeline_task.done():
            self._pipeline_task.cancel()
            self.log.info("⏹️ Đã gửi cancel tới pipeline")
'@

$newAbort = @'
    async def abort(self):
        task = self._pipeline_task
        if task and not task.done():
            self.log.info("⏹️ Cancelling pipeline...")
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._pipeline_task = None
'@

if ($conn.Contains($oldAbort)) {
    $conn = $conn.Replace($oldAbort, $newAbort)
    Write-Host "   ✅ abort async" -ForegroundColor Green
} else {
    Write-Host "   ⚠️ Không match abort" -ForegroundColor Yellow
}

# ----- 5: send_bytes timeout -----
$oldSend = @'
                await self.ws.send_json(meta)
                await self.ws.send_bytes(payload["data"])
'@
$newSend = @'
                await asyncio.wait_for(self.ws.send_json(meta), timeout=5.0)
                await asyncio.wait_for(
                    self.ws.send_bytes(payload["data"]), timeout=10.0
                )
'@

if ($conn.Contains($oldSend)) {
    $conn = $conn.Replace($oldSend, $newSend)
    Write-Host "   ✅ send_bytes timeout" -ForegroundColor Green
}

if ($conn -ne $orig) {
    Write-Utf8 "app\core\connection.py" $conn
    Write-Host "   💾 Đã ghi connection.py" -ForegroundColor Green
}

# ============================================================
# FIX 6 — chat_ws.py
# ============================================================
Write-Host ""
Write-Host "[6/7] chat_ws.py" -ForegroundColor Cyan
Backup "app\routes\chat_ws.py"

$ws = Read-Utf8 "app\routes\chat_ws.py"

$oldFinally = @'
    finally:
        if session_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    await chat_service.close_session(db, session_id)
            except Exception as e:
                log.warning(f"⚠️ Không đóng được session: {e}")
        log.info(f"🔌 Session #{session_id} đóng")
'@

$newFinally = @'
    finally:
        if handler is not None:
            try:
                await handler.abort()
            except Exception:
                pass
        if session_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    await chat_service.close_session(db, session_id)
            except Exception as e:
                log.warning(f"⚠️ Không đóng được session: {e}")
        log.info(f"🔌 Session #{session_id} đóng")
'@

if ($ws.Contains($oldFinally)) {
    $ws = $ws.Replace($oldFinally, $newFinally)
    Write-Utf8 "app\routes\chat_ws.py" $ws
    Write-Host "   ✅ finally abort" -ForegroundColor Green
} else {
    Write-Host "   ⚠️ Không match finally" -ForegroundColor Yellow
}

# ============================================================
# FIX 7 — esp32_ws.py
# ============================================================
Write-Host ""
Write-Host "[7/7] esp32_ws.py" -ForegroundColor Cyan
Backup "app\routes\esp32_ws.py"

$esp = Read-Utf8 "app\routes\esp32_ws.py"

# Xóa import cũ
$oldImport = 'from app.core.providers.vad.energy import EnergyVAD as StreamingAudioBuffer'
if ($esp.Contains($oldImport)) {
    $esp = $esp.Replace($oldImport, '# (removed unused import)')
    Write-Host "   ✅ Xóa import cũ" -ForegroundColor Green
}

$oldVad = @'
    # ✅ VAD đọc từ config
    vad_cfg = config.vad_config
    vad = StreamingAudioBuffer(
        sample_rate=16000,
        frame_duration_ms=config.frame_duration,
        silence_duration_ms=vad_cfg.get("silence_duration_ms", 700),
        min_speech_duration_ms=vad_cfg.get("min_speech_duration_ms", 300),
        energy_margin_db=vad_cfg.get("energy_margin_db", 6.0),
        initial_threshold=vad_cfg.get("initial_threshold", 500.0),
        hangover_ms=vad_cfg.get("hangover_ms", 200),
        pre_speech_ms=vad_cfg.get("pre_speech_ms", 200),
        post_speech_ms=vad_cfg.get("post_speech_ms", 300),
    )
'@

$newVad = @'
    # ✅ VAD theo config.vad_provider
    vad = _make_vad()
    log.info(f"🎤 VAD: {config.vad_provider}")
'@

if ($esp.Contains($oldVad)) {
    $esp = $esp.Replace($oldVad, $newVad)
    Write-Utf8 "app\routes\esp32_ws.py" $esp
    Write-Host "   ✅ Dùng _make_vad()" -ForegroundColor Green
} else {
    Write-Host "   ⚠️ Không match VAD block" -ForegroundColor Yellow
}

# ============================================================
# FIX 8 — config.yaml
# ============================================================
Write-Host ""
Write-Host "[8/8] config.yaml" -ForegroundColor Cyan
Backup "config.yaml"

$cfg = Read-Utf8 "config.yaml"
$cfg = $cfg -replace "(?s)(TTS:\s*\n\s*vieneu:.*?request_timeout:\s*)45(\.0)?", '${1}15.0'
Write-Utf8 "config.yaml" $cfg
Write-Host "   ✅ tts timeout = 15.0" -ForegroundColor Green

# ============================================================
# TEST IMPORT
# ============================================================
Write-Host ""
Write-Host "🧪 Test import..." -ForegroundColor Yellow

Set-Location $root    # ✅ quan trọng: đảm bảo python tìm thấy app

$tests = @(
    @{desc="vieneu"; code="from app.core.providers.tts.vieneu import VieNeuTTSProvider; print('OK')"},
    @{desc="connection"; code="from app.core.connection import ConnectionHandler, _AudioReorderer; print('OK')"},
    @{desc="chat_ws"; code="from app.routes import chat_ws; print('OK')"},
    @{desc="esp32_ws"; code="from app.routes import esp32_ws; print('OK')"}
)

$allOk = $true
foreach ($t in $tests) {
    $out = & python -c $t.code 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   ✅ $($t.desc): $out" -ForegroundColor Green
    } else {
        Write-Host "   ❌ $($t.desc) FAIL:" -ForegroundColor Red
        Write-Host "      $out" -ForegroundColor DarkGray
        $allOk = $false
    }
}

Write-Host ""
if ($allOk) {
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "✅ FIX XONG — tất cả import OK" -ForegroundColor Green
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
} else {
    Write-Host "⚠️ Có lỗi import — kiểm tra output trên" -ForegroundColor Red
}

Write-Host ""
Write-Host "📦 Backup: $bk" -ForegroundColor Cyan
Write-Host ""
Write-Host "BƯỚC TIẾP:" -ForegroundColor Yellow
Write-Host "  1. Kill server cũ (Ctrl+C terminal run.py)" -ForegroundColor White
Write-Host "  2. python run.py" -ForegroundColor White
Write-Host "  3. Test: hỏi 'giá vàng hôm nay'" -ForegroundColor White