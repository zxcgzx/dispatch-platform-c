"""一条命令启动演示：python run.py → http://localhost:8000

依赖：pip install -r backend/requirements.txt（不需要 Node；前端已构建在 backend/app/static/）。
可选参数：--port 8000 --host 127.0.0.1 --no-browser
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    ap = argparse.ArgumentParser(description="课题 4 建模工作台")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    a = ap.parse_args()

    if not (ROOT / "backend" / "app" / "static" / "index.html").exists():
        print("[提示] backend/app/static/ 里没有前端构建产物；只有 API 可用。先在 frontend/ 里运行 npm run build。")
    import uvicorn

    url = f"http://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:{a.port}"
    if not a.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    print(f"建模工作台：{url}")
    uvicorn.run("app.main:app", host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
