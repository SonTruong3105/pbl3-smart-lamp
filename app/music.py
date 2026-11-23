"""Music module — Gộp từ cache.py và resolver.py."""
import asyncio, os, re, shutil, sys, tempfile
from pathlib import Path
from typing import Optional
from loguru import logger

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_CACHE_DIR_MAX_BYTES = 500 * 1024 * 1024


def extract_video_id(text: str) -> Optional[str]:
    """Extract a valid YouTube ID from a URL or a spoken transcript."""
    if not isinstance(text, str):
        return None
    match = re.search(
        r"(?:v=|youtu\.be/|youtube\.com/(?:shorts/|embed/))([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])",
        text,
    )
    if match:
        return match.group(1)
    match = re.search(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", text)
    return match.group(1) if match else None


def music_search_query(text: str) -> Optional[str]:
    """Remove common Vietnamese playback phrasing before YouTube search."""
    if not isinstance(text, str):
        return None
    quoted = re.search(r'[\"“”‘’](.+?)[\"“”‘’]', text)
    if quoted:
        query = quoted.group(1).strip()
    else:
        query = re.sub(r"^.*?\b(?:phát|mở|bật|nghe|play)\b", "", text, count=1, flags=re.I).strip()
        query = re.sub(r"^(?:(?:youtube|nhạc|bài hát|bài)\s*)+", "", query, flags=re.I).strip()
        query = re.sub(r"\b(?:trên youtube|youtube|giúp tôi|cho tôi nghe)\b", " ", query, flags=re.I)
        query = re.sub(r"\b(?:nhé|nha)\b$", "", query, flags=re.I)
    return re.sub(r"\s+", " ", query).strip(" .,!?:;")[:160] or None


class MusicError(Exception):
    pass


def _validate_video_id(video_id: str) -> str:
    if not isinstance(video_id, str) or not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("YouTube video ID khong hop le.")
    return video_id


def _validate_audio(data: bytes) -> None:
    if len(data) < 4:
        raise ValueError("File qua nho.")
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return
    raise ValueError("Khong phai MP3 hop le.")


class MusicCache:
    def __init__(self, root, max_bytes: int = DEFAULT_MAX_BYTES, total_max_bytes: int = DEFAULT_CACHE_DIR_MAX_BYTES):
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.total_max_bytes = total_max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, video_id: str) -> Path:
        return self.root / f"{_validate_video_id(video_id)}.mp3"

    def _prune_if_needed(self, keep_path: Optional[Path] = None) -> None:
        try:
            files = [p for p in self.root.glob("*.mp3") if p.is_file()]
            total = sum(p.stat().st_size for p in files)
            if total <= self.total_max_bytes:
                return
            files.sort(key=lambda p: p.stat().st_mtime)
            for p in files:
                if total <= self.total_max_bytes:
                    break
                if keep_path is not None and p.resolve() == keep_path.resolve():
                    continue
                try:
                    sz = p.stat().st_size
                    p.unlink(missing_ok=True)
                    total -= sz
                except OSError:
                    pass
        except OSError:
            pass

    def get(self, video_id: str) -> Optional[bytes]:
        path = self._path(video_id)
        try:
            if not path.is_file() or path.stat().st_size > self.max_bytes:
                return None
            data = path.read_bytes()
            _validate_audio(data)
            return data
        except (OSError, ValueError):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def put(self, video_id: str, data: bytes) -> None:
        _validate_video_id(video_id)
        if not isinstance(data, bytes) or not data or len(data) > self.max_bytes:
            raise ValueError("Am thanh vuot gioi han.")
        _validate_audio(data)
        temporary = None
        target = self._path(video_id)
        try:
            with tempfile.NamedTemporaryFile("wb", dir=self.root, prefix=".music-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            self._prune_if_needed(keep_path=target)
        except OSError as exc:
            logger.warning(f"MusicCache put failed: {exc}")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


_cache: Optional[MusicCache] = None


def get_cache(root: str = "data/music_cache") -> MusicCache:
    global _cache
    if _cache is None:
        _cache = MusicCache(Path(root))
    return _cache


class YouTubeResolver:
    def __init__(self, cache: MusicCache, timeout: float = 45, enabled: bool = True):
        self.cache = cache
        self.timeout = timeout
        self.enabled = enabled
        self._semaphore = asyncio.Semaphore(2)

    async def search(self, query: str) -> str:
        if not self.enabled:
            raise MusicError("Nhac YouTube chua duoc bat.")
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 160:
            raise ValueError("Ten bai hat khong hop le.")
        async with asyncio.timeout(self.timeout):
            async with self._semaphore:
                result = await self._run([
                    sys.executable, "-m", "yt_dlp",
                    "--flat-playlist", "--no-playlist", "--playlist-end", "1",
                    "--no-warnings", "--quiet", "--print", "id", "--",
                    f"ytsearch1:{query.strip()}",
                ], capture=True)
        ids = [line.strip() for line in result.decode("utf-8", "strict").splitlines() if line.strip()]
        if len(ids) != 1:
            raise MusicError("Khong tim thay bai hat.")
        return _validate_video_id(ids[0])

    async def resolve(self, video_id: str) -> bytes:
        video_id = _validate_video_id(video_id)
        cached = self.cache.get(video_id)
        if cached is not None:
            return cached
        if not self.enabled:
            raise MusicError("Nhac YouTube chua duoc bat.")
        async with asyncio.timeout(self.timeout):
            async with self._semaphore:
                cached = self.cache.get(video_id)
                if cached is not None:
                    return cached
                with tempfile.TemporaryDirectory(dir=self.cache.root) as folder:
                    source = Path(folder) / "source"
                    await self._download(video_id, source)
                    data = await self._transcode(source)
                    self.cache.put(video_id, data)
                    return data

    async def _download(self, video_id: str, target: Path):
        await self._run([
            sys.executable, "-m", "yt_dlp",
            "--no-playlist", "--no-part", "--no-warnings", "--quiet",
            "--socket-timeout", str(self.timeout),
            "--max-filesize", str(self.cache.max_bytes),
            "-f", "worstaudio", "-o", str(target), "--",
            f"https://www.youtube.com/watch?v={video_id}",
        ], output_file=target)
        if not target.is_file() or not 0 < target.stat().st_size <= self.cache.max_bytes:
            raise MusicError("Tep nhac vuot gioi han.")

    async def _transcode(self, source: Path) -> bytes:
        executable = shutil.which("ffmpeg")
        if not executable:
            raise MusicError("Thieu FFmpeg.")
        return await self._run([
            executable, "-hide_banner", "-loglevel", "error",
            "-i", str(source), "-vn", "-ac", "2", "-ar", "44100",
            "-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1",
        ], capture=True)

    async def _run(self, command: list, capture: bool = False, output_file: Path = None) -> bytes:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            data = bytearray()
            if capture:
                while True:
                    chunk = await proc.stdout.read(65536)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > self.cache.max_bytes:
                        raise MusicError("Vuot gioi han.")
            while output_file is not None and proc.returncode is None:
                if output_file.exists() and output_file.stat().st_size > self.cache.max_bytes:
                    raise MusicError("Vuot gioi han.")
                try:
                    await asyncio.wait_for(proc.wait(), 0.1)
                except TimeoutError:
                    pass
            if await proc.wait():
                raise MusicError("Khong tai duoc nhac.")
            return bytes(data)
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()


_default_resolver = YouTubeResolver(get_cache(), enabled=True)


async def search_youtube(query: str) -> str:
    return await _default_resolver.search(query)


async def resolve_mp3(video_id: str) -> bytes:
    return await _default_resolver.resolve(video_id)


# Giữ alias để tương thích ngược với các chỗ đang gọi resolve_ogg
resolve_ogg = resolve_mp3


def ogg_to_browser_mp3(data: bytes) -> bytes:
    return data