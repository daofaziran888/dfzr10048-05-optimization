"""转写版本落库领域服务：把转写结果冻结成带父版本号的版本记录，产出版本记录数据集供字幕包引用与纠错回路消费。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store

DEFAULT_THRESHOLD = 0.70


class TranscriptVersionService(BaseModuleService):
    MODULE = "transcript_version"
    ENTITY = "版本记录"
    OPERATION_TERM = "落库"
    LIST_FIELDS = ["版本编号", "关联任务", "版本号", "父版本号", "变更行数", "变更摘要", "生效阈值", "生效时间", "被引用次数"]
    REQUIRED_FIELDS = ["版本编号", "关联任务", "版本号"]
    STATUS_ORDER = ["草稿", "过渡中", "已生效", "已废止"]
    ACTION_RULES = {"启动过渡": "过渡中", "生效版本": "已生效", "废止版本": "已废止"}
    NEGATIVE_ACTIONS = ["废止版本"]

    # 版本生效阈值在创建时冻结，后续调整只写新版本，已交付版本继续使用自己的阈值。
    def create_version(
        self, version_id: str, task_id: str, version_no: str,
        parent: str, change_lines: int, summary: str,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> tuple[dict[str, Any] | None, str]:
        """创建新转写版本。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("版本编号") == version_id:
                return None, f"版本编号 {version_id} 已存在"
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "版本编号": version_id, "关联任务": task_id,
            "版本号": version_no, "父版本号": parent,
            "变更行数": str(change_lines), "变更摘要": summary,
            "生效阈值": f"{threshold:.2f}",
            "生效时间": "-", "被引用次数": "0",
            "status": "草稿", "pending": True, "abnormal": False,
        }
        rows.append(entry)
        return entry, f"版本 {version_id} 已创建"

    def set_threshold(
        self, version_ref: str, threshold: float,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """调整版本生效阈值，保留变更前口径供发布复核说明。"""
        version = self.resolve_version(version_ref)
        if version is None:
            return False, f"版本 {version_ref} 不存在", None
        before = float(version.get("生效阈值", DEFAULT_THRESHOLD))
        version["阈值变更前"] = f"{before:.2f}"
        version["生效阈值"] = f"{threshold:.2f}"
        return True, (
            f"版本 {version.get('版本编号')} 生效阈值 {before:.2f}->{threshold:.2f}"
        ), version

    def resolve_version(self, version_ref: str) -> dict[str, Any] | None:
        """按版本编号、版本号或记录 id 找到版本。"""
        ref = str(version_ref or "").strip()
        if not ref:
            return None
        for row in store.rows(self.MODULE):
            if ref in {
                str(row.get("版本编号", "")),
                str(row.get("版本号", "")),
                str(row.get("id", "")),
            }:
                return row
        return None

    def effective_threshold(self, version_ref: str) -> float | None:
        """读取版本当前生效阈值。"""
        version = self.resolve_version(version_ref)
        if version is None:
            return None
        try:
            return float(version.get("生效阈值", DEFAULT_THRESHOLD))
        except (TypeError, ValueError):
            return DEFAULT_THRESHOLD

    def get_effective_version(self, task_id: str) -> dict[str, Any] | None:
        """获取指定任务的当前生效版本。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("关联任务") == task_id and r.get("status") == "已生效":
                return r
        return None

    def is_referenced(self, version_id: str) -> bool:
        """检查版本是否被字幕包引用。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("版本编号") == version_id:
                return int(r.get("被引用次数", "0")) > 0
        return False

    def increment_ref_count(self, version_id: str) -> tuple[bool, str]:
        """增加版本的被引用次数。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("版本编号") == version_id:
                current = int(r.get("被引用次数", "0"))
                r["被引用次数"] = str(current + 1)
                return True, f"版本 {version_id} 引用次数: {current + 1}"
        return False, f"版本 {version_id} 不存在"

    def get_versions_by_task(self, task_id: str) -> list[dict[str, Any]]:
        """获取指定任务的全部版本记录，按版本号排序。"""
        rows = store.rows(self.MODULE)
        vers = [r for r in rows if r.get("关联任务") == task_id]
        vers.sort(key=lambda r: r.get("版本号", "v0"))
        return vers