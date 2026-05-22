"""Simple, clean utility function for /test-generate evaluation."""
from datetime import datetime, timedelta


def format_duration(seconds: int) -> str:
    """秒数を人間可読な形式に変換する。

    例:
        45        → "45秒"
        90        → "1分30秒"
        3661      → "1時間1分1秒"
        86400     → "1日0時間"
        90061     → "1日1時間1分1秒"

    制約:
        - seconds は非負整数
        - 0 の場合は "0秒" を返す
    """
    if seconds < 0:
        raise ValueError("seconds must be non-negative")
    if seconds == 0:
        return "0秒"

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}日")
        parts.append(f"{hours}時間")
    elif hours:
        parts.append(f"{hours}時間")
    if minutes or (days or hours) and secs == 0:
        parts.append(f"{minutes}分")
    if secs or not parts:
        parts.append(f"{secs}秒")
    return "".join(parts)
