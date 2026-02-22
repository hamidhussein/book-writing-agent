import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"

BACKEND_LOG = BACKEND_DIR / "backend_dev.log"
FRONTEND_LOG = FRONTEND_DIR / "frontend_dev.log"

DETACHED_FLAGS = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP


def kill_port(port: int) -> None:
    result = subprocess.run(
        ["cmd", "/c", f"netstat -ano | findstr :{port}"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[-1].isdigit():
            pids.add(parts[-1])
    for pid in sorted(pids):
        subprocess.run(["taskkill", "/F", "/PID", pid], check=False, capture_output=True, text=True)


def spawn_backend() -> None:
    log_file = open(BACKEND_LOG, "w", encoding="utf-8")
    subprocess.Popen(
        ["python", "manage.py", "runserver", "127.0.0.1:8000"],
        cwd=str(BACKEND_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=DETACHED_FLAGS,
        close_fds=True,
    )


def spawn_frontend() -> None:
    env = os.environ.copy()
    env["VITE_API_BASE_URL"] = "http://127.0.0.1:8000/api"
    log_file = open(FRONTEND_LOG, "w", encoding="utf-8")
    subprocess.Popen(
        ["cmd", "/c", "npm run dev -- --host 127.0.0.1 --port 5174"],
        cwd=str(FRONTEND_DIR),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=DETACHED_FLAGS,
        close_fds=True,
    )


def main() -> None:
    kill_port(8000)
    kill_port(5174)
    kill_port(8010)
    spawn_backend()
    spawn_frontend()
    print("Restarted backend (8000) and frontend (5174).")


if __name__ == "__main__":
    main()
