import json
import re


def clean_json(text: str) -> str:
    if not text:
        return ""

    text = text.strip()

    # 1. 去掉 markdown 代码块包裹
    if text.startswith("```"):
        # 去掉第一行（``` 或 ```json）
        lines = text.split("\n", 1)
        text = lines[1] if len(lines) > 1 else ""
        # 去掉结尾的 ```
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()

    # 2. 截取第一个 { 到最后一个 }（处理前后解释文字）
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    return text.strip()


def extract_json(text: str) -> dict:
    cleaned = clean_json(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败：{e}，原始返回：{text!r}") from e