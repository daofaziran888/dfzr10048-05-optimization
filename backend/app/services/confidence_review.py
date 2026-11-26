"""置信复核校验领域服务：对低于生效阈值的语音段做人工复核、领取与签名，产出复核条目数据集供转写版本发布复核消费。

发布复核口径：
- 阈值按版本各自生效，版本之间互不污染；已交付的旧版本继续按自己的阈值展示签名。
- 一段是否低置信只看该段置信度与所属版本当前生效阈值，签名必须绑定“该段 + 该版本”。
- 签名是否有效还要求签署口径（领取签名时记录的阈值）不低于版本当前生效阈值，
  按旧阈值领取、迟到提交的签名会失效，必须按新阈值重审。
- 已审段数按“段”去重计数，同一段重复签名不会替邻段通过，也不会增加已审段数。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

VERSION_MODULE = "transcript_version"
SEGMENT_MODULE = "speech_segment"
DEFAULT_THRESHOLD = 0.70
SIGNED = "通过"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class ConfidenceReviewService(BaseModuleService):
    MODULE = "confidence_review"
    ENTITY = "复核条目"
    OPERATION_TERM = "校验"
    LIST_FIELDS = [
        "复核编号", "关联分段", "段置信度", "复核阈值", "复核结论",
        "复核人标识", "领取人", "复核耗时", "回写版本", "签署时间",
    ]
    REQUIRED_FIELDS = ["复核编号", "关联分段", "段置信度"]
    STATUS_ORDER = ["待复核", "复核中", "已通过", "已驳回"]
    ACTION_RULES = {"启动复核": "复核中", "通过条目": "已通过", "驳回条目": "已驳回"}
    NEGATIVE_ACTIONS = ["驳回条目"]

    # ------------------------------------------------------------------
    # 基础口径
    # ------------------------------------------------------------------
    def needs_review(self, segment_confidence: float, threshold: float) -> bool:
        """判断是否需要人工复核：置信度低于生效阈值才需要签名。"""
        return segment_confidence < threshold

    def resolve_version(self, version_ref: str) -> dict[str, Any] | None:
        """按版本编号、版本号或记录 id 找到版本。"""
        ref = str(version_ref or "").strip()
        if not ref:
            return None
        for row in store.rows(VERSION_MODULE):
            if ref in {
                str(row.get("版本编号", "")),
                str(row.get("版本号", "")),
                str(row.get("id", "")),
            }:
                return row
        return None

    def version_threshold(self, version: dict[str, Any]) -> float:
        """读取版本当前生效阈值；历史数据没有该字段时回退到默认阈值。"""
        return _as_float(version.get("生效阈值"), DEFAULT_THRESHOLD)

    def segments_for_version(self, version: dict[str, Any]) -> list[dict[str, Any]]:
        """一个版本覆盖的语音段按任务归属，按起始时间排序。"""
        task_id = version.get("关联任务")
        segments = [
            row for row in store.rows(SEGMENT_MODULE)
            if str(row.get("关联任务")) == str(task_id)
        ]
        segments.sort(key=lambda row: _as_float(row.get("起始毫秒")))
        return segments

    def _version_matches(self, row: dict[str, Any], version: dict[str, Any]) -> bool:
        """复核条目通过回写版本绑定版本，兼容版本编号与版本号两种写法。"""
        ref = str(row.get("回写版本", "")).strip()
        return ref in {
            str(version.get("版本编号", "")),
            str(version.get("版本号", "")),
        }

    def _rows_for(self, segment_id: str, version: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            row for row in store.rows(self.MODULE)
            if str(row.get("关联分段")) == str(segment_id)
            and self._version_matches(row, version)
        ]

    @staticmethod
    def _conclusion(row: dict[str, Any]) -> str:
        return str(row.get("复核结论", "") or "").strip()

    def _signature_state(self, row: dict[str, Any], threshold: float) -> str:
        """返回签名状态：valid（有效）/ stale（按旧阈值签署失效）/ unsigned（未签署）。"""
        if self._conclusion(row) != SIGNED:
            return "unsigned"
        if _as_float(row.get("复核阈值")) + 1e-9 < threshold:
            return "stale"
        return "valid"

    @staticmethod
    def _review_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "review_id": row.get("复核编号"),
            "segment_id": row.get("关联分段"),
            "reviewer": row.get("复核人标识") or row.get("领取人") or "",
            "threshold": _as_float(row.get("复核阈值")),
            "threshold_text": str(row.get("复核阈值", "")),
            "conclusion": row.get("复核结论"),
            "signed_at": row.get("签署时间") or row.get("领取时间") or "",
        }

    def _segment_detail(
        self, segment: dict[str, Any], version: dict[str, Any], threshold: float,
    ) -> dict[str, Any]:
        """单个语音段相对某一版本的覆盖明细。"""
        segment_id = str(segment.get("分段编号", ""))
        confidence = _as_float(segment.get("段置信度"))
        required = confidence < threshold
        rows = self._rows_for(segment_id, version)

        signed_rows = [row for row in rows if self._signature_state(row, threshold) != "unsigned"]
        valid_rows = [row for row in signed_rows if self._signature_state(row, threshold) == "valid"]
        stale_rows = [row for row in signed_rows if self._signature_state(row, threshold) == "stale"]
        open_claims = [
            row for row in rows
            if self._signature_state(row, threshold) == "unsigned"
        ]

        valid_sorted = sorted(valid_rows, key=lambda row: int(row.get("id", 0)), reverse=True)
        valid_signature = self._review_view(valid_sorted[0]) if valid_sorted else None
        stale_signatures = [self._review_view(row) for row in stale_rows]
        for item in stale_signatures:
            item["invalid_reason"] = (
                f"按旧阈值 {item['threshold_text']} 签署，低于当前生效阈值 {threshold:g}，需重审"
            )

        open_claim = None
        if open_claims:
            latest = max(open_claims, key=lambda row: int(row.get("id", 0)))
            open_claim = {
                "review_id": latest.get("复核编号"),
                "claimant": latest.get("领取人") or latest.get("复核人标识") or "",
                "claimed_at": latest.get("领取时间") or "",
                "threshold": _as_float(latest.get("复核阈值")),
                "threshold_text": str(latest.get("复核阈值", "")),
            }

        if not required:
            status = "免签"
            note = f"置信度 {confidence:g} 不低于生效阈值 {threshold:g}，无需签名"
        elif valid_signature:
            status = "已签署"
            note = (
                f"签名有效：{valid_signature['reviewer']} 按阈值 "
                f"{valid_signature['threshold_text']} 签署"
            )
        elif stale_signatures:
            status = "需重审"
            note = (
                f"签名无效：{stale_signatures[0]['reviewer']} 按旧阈值 "
                f"{stale_signatures[0]['threshold_text']} 签署，低于当前生效阈值 "
                f"{threshold:g}，需按新阈值重审"
            )
        elif open_claim and open_claim["claimant"]:
            status = "已领取"
            note = f"{open_claim['claimant']} 已按阈值 {open_claim['threshold_text']} 领取，待签名"
        else:
            status = "待领取"
            note = "低于生效阈值且尚未签名，可领取复核"

        needs_review_by = ""
        if required and not valid_signature:
            if stale_signatures:
                needs_review_by = stale_signatures[0]["reviewer"]
            elif open_claim:
                needs_review_by = open_claim["claimant"]
            else:
                needs_review_by = "待领取"

        return {
            "segment_id": segment_id,
            "confidence": confidence,
            "confidence_text": str(segment.get("段置信度", "")),
            "threshold": threshold,
            "required": required,
            "exempt": not required,
            "signed": valid_signature is not None,
            "signature_valid": valid_signature is not None,
            "status": status,
            "valid_signature": valid_signature,
            "stale_signatures": stale_signatures,
            "open_claim": open_claim,
            "needs_review_by": needs_review_by,
            "note": note,
        }

    # ------------------------------------------------------------------
    # 发布复核
    # ------------------------------------------------------------------
    def build_release_review(self, version_ref: str) -> dict[str, Any]:
        """服务端发布复核明细：按版本生效阈值核对低置信段与签名覆盖。"""
        version = self.resolve_version(version_ref)
        if version is None:
            return {
                "ok": False,
                "message": f"版本 {version_ref} 不存在",
                "segments": [],
                "reviews_needed": [],
                "missing_segments": [],
                "signed_count": 0,
                "required_count": 0,
                "coverage_complete": False,
            }

        threshold = self.version_threshold(version)
        segments = self.segments_for_version(version)
        details = [self._segment_detail(segment, version, threshold) for segment in segments]

        required = [item for item in details if item["required"]]
        covered = [item for item in required if item["signature_valid"]]
        missing = [item for item in required if not item["signature_valid"]]
        exempt = [item for item in details if item["exempt"]]
        complete = not missing

        signatures: list[dict[str, Any]] = []
        for segment in segments:
            for row in self._rows_for(str(segment.get("分段编号", "")), version):
                state = self._signature_state(row, threshold)
                if state == "unsigned":
                    continue
                view = self._review_view(row)
                view.update({
                    "valid": state == "valid",
                    "invalid_reason": (
                        "" if state == "valid" else
                        f"按旧阈值 {view['threshold_text']} 签署，低于当前生效阈值 {threshold:g}"
                    ),
                })
                signatures.append(view)

        reviews_needed = [
            {
                "segment_id": item["segment_id"],
                "reviewer": item["needs_review_by"],
                "reason": item["note"],
            }
            for item in missing
        ]

        if complete:
            message = (
                f"发布复核通过：{version.get('版本编号')} 生效阈值 {threshold:g}，"
                f"{len(covered)}/{len(required)} 个低置信段签名有效"
            )
            if covered:
                message += "；" + "；".join(
                    f"{item['segment_id']} 的有效签名来自 "
                    f"{item['valid_signature']['reviewer']}"
                    f"（阈值 {item['valid_signature']['threshold_text']}）"
                    for item in covered
                )
        else:
            pieces = []
            for item in missing:
                if item["stale_signatures"]:
                    first = item["stale_signatures"][0]
                    pieces.append(
                        f"{item['segment_id']} 的签名（{first['reviewer']}，"
                        f"旧阈值 {first['threshold_text']}）无效，需 {first['reviewer']} 重审"
                    )
                elif item["open_claim"] and item["open_claim"]["claimant"]:
                    pieces.append(
                        f"{item['segment_id']} 由 {item['open_claim']['claimant']} 领取后尚未签名"
                    )
                else:
                    pieces.append(f"{item['segment_id']} 尚缺签名")
            valid_pieces = [
                f"{item['segment_id']} 的有效签名来自 "
                f"{item['valid_signature']['reviewer']}"
                f"（阈值 {item['valid_signature']['threshold_text']}）"
                for item in covered
            ]
            message = (
                f"发布复核未通过：{len(covered)}/{len(required)} 个低置信段签名有效"
                + (f"；有效签名：{'、'.join(valid_pieces)}" if valid_pieces else "")
                + "；待处理：" + "；".join(pieces)
            )

        return {
            "ok": complete,
            "version_id": version.get("版本编号"),
            "version_no": version.get("版本号"),
            "version_status": version.get("status"),
            "task_id": version.get("关联任务"),
            "delivered": version.get("status") == "已生效",
            "threshold": threshold,
            "previous_threshold": _as_float(version.get("阈值变更前"), threshold),
            "threshold_changed": bool(version.get("阈值变更前")),
            "required_count": len(required),
            "signed_count": len(covered),
            "exempt_count": len(exempt),
            "coverage_complete": complete,
            "segments": details,
            "signatures": signatures,
            "missing_segments": [item["segment_id"] for item in missing],
            "reviews_needed": reviews_needed,
            "message": message,
        }

    def release_version(self, version_ref: str, actor: str = "制作人") -> dict[str, Any]:
        """制作人点发布：完成覆盖校验后放行版本生效；未覆盖则原样阻断。"""
        detail = self.build_release_review(version_ref)
        if not detail["ok"]:
            return detail

        version = self.resolve_version(version_ref)
        if version is None:  # pragma: no cover - build_release_review 已经拦截
            return detail
        if version.get("status") != "已生效":
            version["status"] = "已生效"
            version["pending"] = False
            version["abnormal"] = False
            version["生效时间"] = _now()
        detail["version_status"] = version.get("status")
        detail["message"] = (
            f"{actor}发布复核通过：{version.get('版本编号')} 按阈值 "
            f"{detail['threshold']:g} 覆盖 {detail['signed_count']}/{detail['required_count']} 个低置信段"
        )
        return detail

    # ------------------------------------------------------------------
    # 复核待办 / 领取 / 签名
    # ------------------------------------------------------------------
    def build_todo(self, version_ref: str) -> dict[str, Any]:
        """复核员待办：展示每个需签名段的签名有效性、领取人与重审责任。"""
        detail = self.build_release_review(version_ref)
        if not detail.get("version_id"):
            return detail

        items = [item for item in detail["segments"] if item["required"]]
        pending = [item for item in items if not item["signature_valid"]]
        detail["items"] = items
        detail["pending_count"] = len(pending)
        if pending:
            detail["message"] = (
                f"待办 {len(pending)} 段待处理；"
                + "；".join(
                    f"{item['segment_id']}：{item['note']}"
                    f"（{('需重审人 ' + item['needs_review_by']) if item['needs_review_by'] else '待领取'}）"
                    for item in pending
                )
            )
        else:
            detail["message"] = (
                f"待办已清零：{detail['signed_count']}/{detail['required_count']} "
                f"个低置信段签名有效，阈值 {detail['threshold']:g}"
            )
        return detail

    def _next_review_id(self) -> str:
        max_no = 0
        for row in store.rows(self.MODULE):
            code = str(row.get("复核编号", ""))
            tail = code.rsplit("-", 1)[-1]
            if tail.isdigit():
                max_no = max(max_no, int(tail))
        return f"CFRV-{max_no + 1:04d}"

    def _segment(self, segment_id: str) -> dict[str, Any] | None:
        for row in store.rows(SEGMENT_MODULE):
            if str(row.get("分段编号")) == str(segment_id):
                return row
        return None

    def claim_segment(
        self, segment_id: str, version_ref: str, reviewer: str,
    ) -> dict[str, Any]:
        """复核员从待办领取一个仍缺有效签名的段，签名口径锁定为领取时的阈值。"""
        version = self.resolve_version(version_ref)
        if version is None:
            return {"ok": False, "message": f"版本 {version_ref} 不存在"}
        segment = self._segment(segment_id)
        if segment is None:
            return {"ok": False, "message": f"语音段 {segment_id} 不存在"}

        threshold = self.version_threshold(version)
        item = self._segment_detail(segment, version, threshold)
        if not item["required"]:
            return {"ok": False, "message": item["note"], "item": item}
        if item["signature_valid"]:
            return {"ok": False, "message": f"{segment_id} 已有有效签名，无需重复领取", "item": item}
        if item["open_claim"]:
            claimant = item["open_claim"]["claimant"]
            claimed_threshold = _as_float(item["open_claim"]["threshold"])
            if claimant == reviewer and claimed_threshold + 1e-9 < threshold:
                # 领取口径已经过期：同一位复核员重新领取即按当前阈值换发口径。
                stale = next(
                    row for row in self._rows_for(segment_id, version)
                    if row.get("复核编号") == item["open_claim"]["review_id"]
                )
                stale["复核阈值"] = f"{threshold:.2f}"
                stale["领取时间"] = _now()
                return {
                    "ok": True,
                    "message": (
                        f"{reviewer} 已按新阈值 {threshold:.2f} 重新领取 {segment_id}"
                        f"（原口径 {claimed_threshold:.2f} 作废）"
                    ),
                    "review_id": stale["复核编号"],
                    "threshold": threshold,
                    "item": self._segment_detail(segment, version, threshold),
                }
            return {
                "ok": False,
                "message": f"{segment_id} 已由 {claimant} 按阈值 {threshold:g} 领取，待其签名或释放",
                "item": item,
                "review_id": item["open_claim"]["review_id"],
            }

        row = {
            "id": max((int(r.get("id", 0)) for r in store.rows(self.MODULE)), default=0) + 1,
            "status": "复核中",
            "pending": True,
            "abnormal": False,
            "复核编号": self._next_review_id(),
            "关联分段": segment_id,
            "段置信度": str(segment.get("段置信度", "")),
            "复核阈值": f"{threshold:.2f}",
            "复核结论": "-",
            "复核人标识": reviewer,
            "领取人": reviewer,
            "复核耗时": "0",
            "回写版本": str(version.get("版本编号")),
            "领取时间": _now(),
            "签署时间": "",
        }
        store.rows(self.MODULE).append(row)
        return {
            "ok": True,
            "message": (
                f"{reviewer} 已领取 {segment_id}（版本 {version.get('版本编号')}，"
                f"签名口径阈值 {threshold:.2f}）"
            ),
            "review_id": row["复核编号"],
            "threshold": threshold,
            "item": self._segment_detail(segment, version, threshold),
        }

    def submit_signature(
        self, segment_id: str, version_ref: str, reviewer: str,
        conclusion: str = SIGNED,
    ) -> dict[str, Any]:
        """提交段签名：签名绑定该段与该版本，按领取时口径判定是否仍然有效。"""
        version = self.resolve_version(version_ref)
        if version is None:
            return {"ok": False, "message": f"版本 {version_ref} 不存在", "counted": False}
        segment = self._segment(segment_id)
        if segment is None:
            return {"ok": False, "message": f"语音段 {segment_id} 不存在", "counted": False}

        threshold = self.version_threshold(version)
        before_detail = self.build_release_review(str(version.get("版本编号")))
        item = self._segment_detail(segment, version, threshold)
        if not item["required"]:
            return {
                "ok": True,
                "message": f"{segment_id} 置信度不低于生效阈值 {threshold:g}，无需签名，不计入已审段数",
                "counted": False,
                "signature_valid": False,
                "signed_count": before_detail["signed_count"],
                "required_count": before_detail["required_count"],
                "coverage_complete": before_detail["coverage_complete"],
                "item": before_detail,
            }
        if item["signature_valid"]:
            return {
                "ok": True,
                "message": (
                    f"{segment_id} 已有有效签名（{item['valid_signature']['reviewer']}），"
                    f"重复签署不增加已审段数"
                ),
                "counted": False,
                "signature_valid": True,
                "review_id": item["valid_signature"]["review_id"],
                "signed_count": before_detail["signed_count"],
                "required_count": before_detail["required_count"],
                "coverage_complete": before_detail["coverage_complete"],
                "item": before_detail,
            }

        # 按领取时的口径签署；领取在别人手里时不能替他签，交给领取人提交或重新领取。
        open_rows = [
            row for row in self._rows_for(segment_id, version)
            if self._signature_state(row, threshold) == "unsigned"
        ]
        if open_rows:
            row = max(open_rows, key=lambda entry: int(entry.get("id", 0)))
            holder = row.get("领取人") or row.get("复核人标识") or ""
            if holder and holder != reviewer:
                return {
                    "ok": False,
                    "message": (
                        f"{segment_id} 已由 {holder} 按阈值 "
                        f"{row.get('复核阈值')} 领取，仅在本人提交或重新领取后才能签名"
                    ),
                    "counted": False,
                    "signature_valid": False,
                    "signed_count": before_detail["signed_count"],
                    "required_count": before_detail["required_count"],
                    "item": before_detail,
                }
        else:
            claim = self.claim_segment(segment_id, str(version.get("版本编号")), reviewer)
            if not claim.get("ok"):
                return {**claim, "counted": False}
            row = next(
                entry for entry in self._rows_for(segment_id, version)
                if entry.get("复核编号") == claim["review_id"]
            )

        before = self.build_release_review(str(version.get("版本编号")))["signed_count"]

        signed_threshold = _as_float(row.get("复核阈值"), threshold)
        row["复核结论"] = conclusion
        row["复核人标识"] = reviewer
        row["签署时间"] = _now()
        row["复核耗时"] = "0"
        signed_ok = conclusion == SIGNED
        row["status"] = "已通过" if signed_ok else "已驳回"
        row["pending"] = not signed_ok
        row["abnormal"] = not signed_ok

        state = self._signature_state(row, threshold)
        valid = state == "valid"
        after_detail = self.build_release_review(str(version.get("版本编号")))
        counted = after_detail["signed_count"] > before

        if not signed_ok:
            message = f"{segment_id} 签名结论为{conclusion}，不构成有效签名"
        elif not valid:
            message = (
                f"{segment_id} 签名已登记但无效：按领取时阈值 {signed_threshold:g} 签署，"
                f"低于当前生效阈值 {threshold:g}，需按新阈值重审"
            )
        elif counted:
            message = (
                f"{segment_id} 签名有效（{reviewer}，阈值 {signed_threshold:g}），"
                f"已审段数 {before}->{after_detail['signed_count']}"
            )
        else:
            message = (
                f"{segment_id} 签名有效（{reviewer}，阈值 {signed_threshold:g}），"
                f"该段此前已有有效签名，已审段数保持 {after_detail['signed_count']}"
            )

        return {
            "ok": True,
            "message": message,
            "counted": counted,
            "signature_valid": valid,
            "invalid_reason": "" if valid or not signed_ok else (
                f"按旧阈值 {signed_threshold:g} 签署，低于当前生效阈值 {threshold:g}"
            ),
            "review_id": row.get("复核编号"),
            "signed_threshold": signed_threshold,
            "signed_count": after_detail["signed_count"],
            "required_count": after_detail["required_count"],
            "coverage_complete": after_detail["coverage_complete"],
            "item": after_detail,
        }

    # ------------------------------------------------------------------
    # 兼容原有查询与回写接口
    # ------------------------------------------------------------------
    def submit_review(
        self, review_id: str, conclusion: str, reviewer: str,
        elapsed_seconds: int, writeback_version: str,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """提交复核结论并回写版本（保留给既有调用方）。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("复核编号") == review_id:
                r["复核结论"] = conclusion
                r["复核人标识"] = reviewer
                r["复核耗时"] = str(elapsed_seconds)
                r["回写版本"] = writeback_version
                r["签署时间"] = _now()
                if conclusion == "通过":
                    r["status"] = "已通过"
                    r["pending"] = False
                else:
                    r["status"] = "已驳回"
                    r["pending"] = True
                    r["abnormal"] = True
                return True, f"复核 {review_id} 结论: {conclusion}", dict(r)
        return False, f"复核条目 {review_id} 不存在", None

    def get_reviews_by_segment(self, segment_id: str) -> list[dict[str, Any]]:
        """获取指定语音段的所有复核条目。"""
        rows = store.rows(self.MODULE)
        return [r for r in rows if r.get("关联分段") == segment_id]

    def get_reviews_by_version(self, version_id: str) -> list[dict[str, Any]]:
        """获取回写到指定版本的所有复核条目。"""
        version = self.resolve_version(version_id) or {"版本编号": version_id}
        rows = store.rows(self.MODULE)
        return [r for r in rows if self._version_matches(r, version)]

    def all_passed_for_version(self, version_id: str) -> bool:
        """检查指定版本的发布覆盖是否完整（每段都有对应段和版本的有效签名）。"""
        detail = self.build_release_review(version_id)
        return bool(detail.get("coverage_complete"))
