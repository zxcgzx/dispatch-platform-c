"""把 backend/app/features.py 的功能登记表导出成前端离线兜底文件 frontend/src/features.fallback.json。

改了 features.py 之后运行一次：python scripts/gen_features.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.features import feature_response  # noqa: E402

out = ROOT / "frontend" / "src" / "features.fallback.json"
out.write_text(json.dumps(feature_response(), ensure_ascii=False, indent=1), encoding="utf-8")
print(f"写出 {out}（{len(feature_response()['features'])} 项）")
