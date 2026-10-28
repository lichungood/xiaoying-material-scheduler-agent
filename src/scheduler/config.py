"""Explicit, non-executable private config loader; never logs config values."""
from pathlib import Path

ALLOWED_NAMES = {"LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"}


def read_private_config(path: Path) -> dict[str, str]:
    settings = {}
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or name not in ALLOWED_NAMES or name in settings:
            raise ValueError(f"私有配置第 {number} 行字段无效或重复；配置内容未输出")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"私有配置第 {number} 行引号不匹配；配置内容未输出")
            value = value[1:-1]
        if "\x00" in value:
            raise ValueError(f"私有配置第 {number} 行含非法字符；配置内容未输出")
        settings[name] = value
    return settings
