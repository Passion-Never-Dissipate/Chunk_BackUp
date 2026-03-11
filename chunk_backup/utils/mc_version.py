from typing import Optional
import re


def is_version_ge_26_1(version: Optional[str]) -> bool:
    """
    判断 Minecraft 版本是否 ≥ 26.1 正式版 或 ≥ 26.1 Snapshot 6。
    支持格式：
        - 正式版/预发布/候选：1.21, 1.21.1, 26.1, 26.1 Pre-Release 2, 26.1 Release Candidate 3
        - 新版快照：26.1 Snapshot 6, 26.2 Snapshot 1
        - 经典快照：26w06a, 26w07b
    返回值：
        True  - 版本满足要求
        False - 版本不满足、无法识别或为 None
    """
    if version is None:
        return False

    # 去除常见后缀（与原函数保持一致）
    if version.endswith(' Unobfuscated'):
        version = version[:-14]

    # ---------- 1. 匹配正式版/预发布/候选 ----------
    # 正则：捕获主、次、补丁号，后缀可选（但不影响数值比较）
    m = re.match(
        r'^(?P<major>\d+)\.(?P<minor>\d+)(\.(?P<patch>\d+))?'
        r'(?: Pre-Release \d+| Release Candidate \d+)?$',
        version
    )
    if m:
        major = int(m.group('major'))
        minor = int(m.group('minor'))
        patch = int(m.group('patch')) if m.group('patch') else 0
        return (major, minor, patch) >= (26, 1, 0)

    # ---------- 2. 匹配新版快照（如 26.1 Snapshot 6）----------
    m = re.match(
        r'^(?P<major>\d+)\.(?P<minor>\d+)(\.(?P<patch>\d+))? Snapshot (?P<num>\d+)$',
        version
    )
    if m:
        major = int(m.group('major'))
        minor = int(m.group('minor'))
        num = int(m.group('num'))
        # 版本高于 26.1 → 自动满足
        if (major, minor) > (26, 1):
            return True
        # 正好是 26.1 → 需快照序号 ≥ 6
        if (major, minor) == (26, 1):
            return num >= 6
        # 低于 26.1 → 不满足
        return False

    # ---------- 3. 匹配经典快照（如 26w06a）----------
    m = re.match(r'^(?P<year>\d{2})w(?P<week>\d{2})[a-z]$', version)
    if m:
        year = int(m.group('year'))
        week = int(m.group('week'))
        # 经典快照：年份 ≥ 26 且 周数 ≥ 6
        return (year, week) >= (26, 6)

    # ---------- 4. 未知格式 ----------
    return False
