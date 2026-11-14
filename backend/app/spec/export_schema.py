"""导出 JSON Schema，供前端 json2ts 生成类型：python backend/app/spec/export_schema.py → spec.schema.json。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.spec.schema import ModelSpec  # noqa: E402

out = Path(__file__).with_name("spec.schema.json")
# mode="serialization"：带默认值的字段在后端响应里总是存在，前端类型里就应是必填，而不是可选
out.write_text(json.dumps(ModelSpec.model_json_schema(mode="serialization"), ensure_ascii=False, indent=2), encoding="utf-8")
print("写出", out)
