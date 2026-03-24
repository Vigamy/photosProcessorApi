import os
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path

INTERVAL = int(os.getenv("INTERVAL", "30"))
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "3"))
DIR_NAME = os.getenv("DIR_NAME", "sys_cache")
ONEDRIVE = os.getenv("OneDrive") or os.getenv("ONEDRIVE")
BASE_DIR = Path(os.getenv("BASE_DIR", Path(ONEDRIVE or Path.home()) / DIR_NAME))
IMG_DIR = BASE_DIR / os.getenv("IMG_DIR_NAME", "img")
COUNTER_FILE = BASE_DIR / os.getenv("COUNTER_FILE_NAME", "counter.txt")
STATUS_FILE = BASE_DIR / os.getenv("STATUS_FILE_NAME", "status.txt")


def create_dirs() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)


def load_counter() -> int:
    if COUNTER_FILE.exists():
        try:
            return int(COUNTER_FILE.read_text(encoding="utf-8").strip())
        except ValueError:
            return 0
    return 0


def save_counter(counter: int) -> None:
    COUNTER_FILE.write_text(str(counter), encoding="utf-8")


def save_number(counter: int) -> None:
    number_file = BASE_DIR / f"{counter}.txt"
    number_file.write_text(str(counter), encoding="utf-8")


def capture_screenshot(destination: Path) -> bool:
    try:
        import mss
        import mss.tools

        with mss.mss() as sct:
            monitor = sct.monitors[1]
            shot = sct.grab(monitor)
            mss.tools.to_png(shot.rgb, shot.size, output=str(destination))
            return True
    except Exception:
        pass

    try:
        import pyautogui

        image = pyautogui.screenshot()
        image.save(destination)
        return True
    except Exception as exc:
        print(f"[WARN] screenshot failed: {exc}")
        return False


def send_screenshot_via_curl(image_path: Path) -> None:
    """
    Use one of the two modes below:
    1) CURL_UPLOAD_CMD='curl -X POST https://api.exemplo/upload -F "file=@{file}"'
       (must include {file} placeholder)
    2) API_UPLOAD_URL='https://api.exemplo/upload'
       API_UPLOAD_HEADER='Authorization: Bearer TOKEN' (optional)
    """
    curl_template = os.getenv("CURL_UPLOAD_CMD", "").strip()

    if curl_template:
        cmd = shlex.split(curl_template.replace("{file}", str(image_path)))
    else:
        api_url = os.getenv("API_UPLOAD_URL", "").strip()
        if not api_url:
            print("[INFO] upload skipped: configure CURL_UPLOAD_CMD or API_UPLOAD_URL")
            return

        cmd = ["curl", "-sS", "-X", "POST", api_url, "-F", f"file=@{image_path}"]
        header = os.getenv("API_UPLOAD_HEADER", "").strip()
        if header:
            cmd.extend(["-H", header])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(f"[WARN] curl upload failed ({result.returncode}): {result.stderr.strip()}")
        else:
            print("[INFO] screenshot uploaded")
    except FileNotFoundError:
        print("[WARN] curl not found in PATH")


def heartbeat() -> None:
    STATUS_FILE.write_text(datetime.now().isoformat(), encoding="utf-8")


def cleanup_old_files() -> None:
    now = time.time()
    retention_seconds = RETENTION_DAYS * 24 * 60 * 60

    for file_path in list(BASE_DIR.glob("*.txt")) + list(IMG_DIR.glob("*.png")):
        if file_path in (COUNTER_FILE, STATUS_FILE):
            continue
        if now - file_path.stat().st_mtime > retention_seconds:
            file_path.unlink(missing_ok=True)


def main_loop() -> None:
    create_dirs()
    counter = load_counter()

    while True:
        counter += 1
        save_counter(counter)
        save_number(counter)

        screenshot_file = IMG_DIR / f"{counter}.png"
        if capture_screenshot(screenshot_file):
            send_screenshot_via_curl(screenshot_file)

        heartbeat()
        cleanup_old_files()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main_loop()
