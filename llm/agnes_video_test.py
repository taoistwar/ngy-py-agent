"""Manual smoke test for the Agnes Video 2.5 text-to-video API.

Docs: https://www.agnes-ai.cn/zh-Hans/docs/agnes-video-25

Flow: POST /v1/videos -> poll GET /agnesapi -> (optional) download the mp4.

Usage:
    uv run python llm/agnes_video_test.py --dry-run
    uv run python llm/agnes_video_test.py
    uv run python llm/agnes_video_test.py --seconds 8 --size 1080P --download

The API key is read from ``AGNES_API_KEY``; when the variable is absent the
repository root ``.env`` is consulted as a fallback.
"""

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

MODEL = "agnes-video-2.5"
CREATE_URL = "https://api.agnes-ai.cn/v1/videos"
QUERY_URL = "https://api.agnes-ai.cn/agnesapi"

TEXT_MODE = "text"
SIZES = ("720P", "1080P", "1K", "2K")
ASPECT_RATIOS = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
SECONDS_MIN, SECONDS_MAX = 4, 12

TERMINAL_STATUSES = {"completed", "failed"}
POLL_INTERVAL_SECONDS = 1.5
POLL_TIMEOUT_SECONDS = 600.0
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_BACKOFF_SECONDS = 20.0
DOWNLOAD_CHUNK_BYTES = 1 << 20

DEFAULT_PROMPT = (
    "雨后的未来城市街道，霓虹灯倒映在湿润的路面上，一辆银色跑车缓慢驶过水洼，"
    "镜头低角度跟拍后缓缓拉升，电影级光影与体积雾，写实风格"
)


def _load_dotenv_file(path: Path) -> None:
    """Fill missing environment variables from a ``KEY=value`` file."""
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate one sample video with Agnes Video 2.5.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Scene description.")
    parser.add_argument("--seconds", default="5", help=f'Clip length, "{SECONDS_MIN}"-"{SECONDS_MAX}".')
    parser.add_argument("--size", default="720P", choices=SIZES, help="Resolution tier.")
    parser.add_argument("--aspect-ratio", default="16:9", choices=ASPECT_RATIOS, help="Frame ratio.")
    parser.add_argument("--seed", type=int, default=None, help="Optional seed for reproducibility.")
    parser.add_argument("--poll-interval", type=float, default=POLL_INTERVAL_SECONDS, help="Seconds between polls.")
    parser.add_argument("--poll-timeout", type=float, default=POLL_TIMEOUT_SECONDS, help="Give up after N seconds.")
    parser.add_argument("--download", action="store_true", help="Save the finished mp4 locally.")
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR, help="Where --download writes the file.")
    parser.add_argument("--dry-run", action="store_true", help="Print the request payload and exit.")
    return parser.parse_args(argv)


def validate_seconds(raw: str) -> str:
    """The API wants the length as a string; reject values it would 400 on."""
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"--seconds must be an integer, got {raw!r}") from exc
    if not SECONDS_MIN <= value <= SECONDS_MAX:
        raise SystemExit(f"--seconds must be between {SECONDS_MIN} and {SECONDS_MAX}, got {value}")
    return str(value)


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    """Text mode accepts no media fields, so only the shared options are sent."""
    payload: dict[str, Any] = {
        "model": MODEL,
        "prompt": args.prompt,
        "mode": TEXT_MODE,
        "seconds": validate_seconds(args.seconds),
        "size": args.size,
        "aspect_ratio": args.aspect_ratio,
        "n": 1,
    }
    if args.seed is not None:
        payload["seed"] = args.seed
    return payload


def resolve_api_key() -> str:
    _load_dotenv_file(ENV_PATH)
    api_key = (os.getenv("AGNES_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("AGNES_API_KEY is not set; export it or add it to the repository .env")
    return api_key


def make_session(api_key: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    return session


def _json_body(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:  # requests wraps JSONDecodeError into a ValueError subclass
        raise SystemExit(f"HTTP {response.status_code} returned non-JSON body: {response.text[:200]!r}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"unexpected response shape: {type(data).__name__}")
    return data


def _raise_for_status(response: requests.Response) -> None:
    if response.status_code < 400:
        return
    raise SystemExit(f"HTTP {response.status_code} from {response.url}: {response.text.strip()[:500]}")


def create_video(session: requests.Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Create the task and return ``video_id`` plus the queued task metadata."""
    print(f"[1/4] POST {CREATE_URL} (mode={payload['mode']}, seconds={payload['seconds']}, size={payload['size']})")
    response = session.post(CREATE_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    _raise_for_status(response)
    data = _json_body(response)

    video_id = data.get("video_id") or data.get("id")
    if not video_id:
        raise SystemExit(f"create response carries no video_id: {json.dumps(data, ensure_ascii=False)}")
    print(f"      task_id={data.get('task_id')} video_id={video_id} status={data.get('status')}")
    return data


def _query_task(session: requests.Session, video_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """One poll. Returns ``(payload, retry_reason)``; payload is None while retrying."""
    params = {"video_id": video_id, "model_name": MODEL}
    try:
        response = session.get(QUERY_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return None, f"network error: {exc}"
    if response.status_code == 429:
        return None, "rate limited (429)"
    if response.status_code >= 500:
        return None, f"server error ({response.status_code})"
    _raise_for_status(response)
    return _json_body(response), None


def poll_video(session: requests.Session, video_id: str, interval: float, timeout: float) -> dict[str, Any]:
    """Poll until the task is ``completed`` or ``failed``, with backoff on retryable errors."""
    deadline = time.monotonic() + timeout
    backoff = interval
    last_status = "unknown"
    while True:
        data, retry_reason = _query_task(session, video_id)
        if retry_reason is None:
            backoff = interval
            last_status = str(data.get("status"))
            print(f"      status={last_status} progress={data.get('progress')}")
            if last_status in TERMINAL_STATUSES:
                return data
            delay = interval
        else:
            delay = min(backoff, MAX_BACKOFF_SECONDS)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            print(f"      {retry_reason}; retrying in {delay:.1f}s")

        if time.monotonic() + delay >= deadline:
            raise SystemExit(
                f"polling exceeded {timeout:.0f}s (last status={last_status}); "
                f"query later with video_id={video_id}"
            )
        time.sleep(delay)


def _error_message(result: dict[str, Any]) -> str:
    error = result.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or "video generation failed")
    return str(error) if error else "video generation failed"


def _download_name(url: str) -> str:
    name = Path(urlparse(url).path).name
    if not name:
        name = f"agnes_video_{int(time.time())}.mp4"
    return name if Path(name).suffix else f"{name}.mp4"


def download_video(session: requests.Session, url: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    destination = out_dir / _download_name(url)
    with session.get(url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        _raise_for_status(response)
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                handle.write(chunk)
    return destination


def finish(session: requests.Session, result: dict[str, Any], args: argparse.Namespace) -> int:
    if result.get("status") == "failed":
        raise SystemExit(f"generation failed: {_error_message(result)}")

    url = str(result.get("url") or "").strip()
    if not url:
        raise SystemExit(f"status is completed but no url is present: {json.dumps(result, ensure_ascii=False)}")
    print(f"[4/4] completed: {url}")

    if args.download:
        path = download_video(session, url, args.out_dir)
        print(f"      saved to {path} ({path.stat().st_size / (1 << 20):.1f} MiB)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_payload(args)

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    session = make_session(resolve_api_key())
    created = create_video(session, payload)

    print(f"[2/4] polling {QUERY_URL} every {args.poll_interval}s (limit {args.poll_timeout:.0f}s)")
    result = poll_video(session, created["video_id"], args.poll_interval, args.poll_timeout)

    print("[3/4] rendering response")
    return finish(session, result, args)


if __name__ == "__main__":
    raise SystemExit(main())
