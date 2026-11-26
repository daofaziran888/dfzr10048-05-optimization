"""发布覆盖复核测试：按版本阈值核对低置信段与签名，覆盖领取、迟到签名与重复签署口径。"""
from __future__ import annotations

import uuid

import pytest

from app.services.confidence_review import ConfidenceReviewService
from app.services.transcript_version import TranscriptVersionService
from app.store import store


def _seed_task(segments: list[tuple[str, float]], threshold: float) -> tuple[str, str]:
    """建一个独立任务/版本，并按其关联任务写入语音段，避免用例之间互相污染。"""
    suffix = uuid.uuid4().hex[:8]
    task_id = f"TASK-{suffix}"
    version_code = f"TRSV-{suffix}"
    for offset, (segment_id, confidence) in enumerate(segments):
        store.rows("speech_segment").append({
            "id": max((int(r.get("id", 0)) for r in store.rows("speech_segment")), default=0) + 1,
            "status": "已对齐", "pending": False, "abnormal": False,
            "分段编号": segment_id, "关联任务": task_id,
            "起始毫秒": str(offset * 3000), "结束毫秒": str((offset + 1) * 3000),
            "段内文本": "测试段", "段置信度": f"{confidence:.2f}",
            "静音前毫秒": "100", "重叠标记": "无",
        })
    versions = TranscriptVersionService()
    entry, _ = versions.create_version(
        version_code, task_id, "v1", "-", 1, "测试版本", threshold,
    )
    assert entry is not None
    return task_id, version_code


def _count_reviews(segment_id: str, version_code: str) -> int:
    return len([
        row for row in store.rows("confidence_review")
        if row.get("关联分段") == segment_id and row.get("回写版本") == version_code
    ])


class TestReleaseCoverage:
    def test_release_blocked_until_every_low_confidence_segment_signed(self):
        seg_a, seg_b = f"SEG-A-{uuid.uuid4().hex[:6]}", f"SEG-B-{uuid.uuid4().hex[:6]}"
        _, version = _seed_task([(seg_a, 0.62), (seg_b, 0.72), (f"SEG-C-{uuid.uuid4().hex[:6]}", 0.95)], 0.80)
        svc = ConfidenceReviewService()

        detail = svc.build_release_review(version)
        assert not detail["ok"]
        assert detail["required_count"] == 2
        assert detail["signed_count"] == 0
        assert set(detail["missing_segments"]) == {seg_a, seg_b}

        assert svc.submit_signature(seg_a, version, "reviewer_a")["counted"]
        detail = svc.build_release_review(version)
        assert not detail["ok"], "只签一段不能替邻段通过"
        assert detail["signed_count"] == 1
        assert detail["missing_segments"] == [seg_b]

        assert svc.submit_signature(seg_b, version, "reviewer_b")["counted"]
        detail = svc.build_release_review(version)
        assert detail["ok"] and detail["coverage_complete"]
        assert detail["signed_count"] == detail["required_count"] == 2

    def test_publish_passes_only_with_full_coverage(self):
        seg_a, seg_b = f"SEG-{uuid.uuid4().hex[:6]}", f"SEG-{uuid.uuid4().hex[:6]}"
        _, version = _seed_task([(seg_a, 0.62), (seg_b, 0.72)], 0.80)
        svc = ConfidenceReviewService()

        blocked = svc.release_version(version)
        assert not blocked["ok"]
        assert store.rows("transcript_version")[
            next(i for i, r in enumerate(store.rows("transcript_version"))
                 if r.get("版本编号") == version)
        ]["status"] == "草稿"

        svc.submit_signature(seg_a, version, "reviewer_a")
        svc.submit_signature(seg_b, version, "reviewer_b")
        released = svc.release_version(version)
        assert released["ok"]
        assert "发布复核通过" in released["message"]

    def test_duplicate_signature_does_not_inflate_signed_count(self):
        seg_a = f"SEG-{uuid.uuid4().hex[:6]}"
        _, version = _seed_task([(seg_a, 0.62)], 0.80)
        svc = ConfidenceReviewService()

        first = svc.submit_signature(seg_a, version, "reviewer_a")
        assert first["counted"] and first["signed_count"] == 1
        second = svc.submit_signature(seg_a, version, "reviewer_a")
        assert not second["counted"]
        assert second["signed_count"] == 1
        assert "不增加已审段数" in second["message"]

    def test_signature_does_not_leak_between_segments(self):
        seg_a, seg_b = f"SEG-{uuid.uuid4().hex[:6]}", f"SEG-{uuid.uuid4().hex[:6]}"
        _, version = _seed_task([(seg_a, 0.62), (seg_b, 0.72)], 0.80)
        svc = ConfidenceReviewService()

        svc.submit_signature(seg_a, version, "reviewer_a")
        detail = svc.build_release_review(version)
        by_segment = {item["segment_id"]: item for item in detail["segments"]}
        assert by_segment[seg_a]["signature_valid"]
        assert not by_segment[seg_b]["signature_valid"]

    def test_signature_requires_same_version(self):
        seg_a = f"SEG-{uuid.uuid4().hex[:6]}"
        _, version = _seed_task([(seg_a, 0.62)], 0.80)
        other_task, other_version = _seed_task([(seg_a, 0.62)], 0.80)
        svc = ConfidenceReviewService()

        svc.submit_signature(seg_a, other_version, "reviewer_a")
        detail = svc.build_release_review(version)
        assert detail["signed_count"] == 0, "另一版本上的签名不能覆盖本版本"
        assert svc.build_release_review(other_version)["signed_count"] == 1


class TestThresholdRaise:
    def test_old_threshold_claim_becomes_invalid_after_raise(self):
        seg_a, seg_b = f"SEG-{uuid.uuid4().hex[:6]}", f"SEG-{uuid.uuid4().hex[:6]}"
        _, version = _seed_task([(seg_a, 0.62), (seg_b, 0.72)], 0.70)
        svc = ConfidenceReviewService()

        assert svc.claim_segment(seg_a, version, "reviewer_a")["ok"]
        TranscriptVersionService().set_threshold(version, 0.80)

        late = svc.submit_signature(seg_a, version, "reviewer_a")
        assert late["signature_valid"] is False
        assert late["counted"] is False
        assert "旧阈值" in late["message"] or "重审" in late["message"]

        fresh = svc.submit_signature(seg_b, version, "reviewer_b")
        assert fresh["signature_valid"] and fresh["counted"]

        detail = svc.build_release_review(version)
        assert not detail["ok"]
        assert detail["signed_count"] == 1
        assert detail["missing_segments"] == [seg_a]
        stale = next(item for item in detail["segments"] if item["segment_id"] == seg_a)
        assert stale["stale_signatures"]
        assert stale["needs_review_by"] == "reviewer_a"
        assert "旧阈值" in detail["message"]

    def test_todo_explains_valid_signature_and_remaining_reviewer(self):
        seg_a, seg_b = f"SEG-{uuid.uuid4().hex[:6]}", f"SEG-{uuid.uuid4().hex[:6]}"
        _, version = _seed_task([(seg_a, 0.62), (seg_b, 0.72)], 0.70)
        svc = ConfidenceReviewService()
        svc.claim_segment(seg_a, version, "reviewer_a")
        TranscriptVersionService().set_threshold(version, 0.80)
        svc.submit_signature(seg_a, version, "reviewer_a")
        svc.submit_signature(seg_b, version, "reviewer_b")

        todo = svc.build_todo(version)
        assert todo["pending_count"] == 1
        by_segment = {item["segment_id"]: item for item in todo["items"]}
        assert by_segment[seg_b]["signature_valid"]
        assert by_segment[seg_a]["status"] == "需重审"
        assert by_segment[seg_a]["needs_review_by"] == "reviewer_a"
        assert "需重审" in todo["message"]

    def test_delivered_version_keeps_own_threshold_and_signature(self):
        seg_a = f"SEG-{uuid.uuid4().hex[:6]}"
        _, version = _seed_task([(seg_a, 0.62)], 0.70)
        svc = ConfidenceReviewService()
        svc.submit_signature(seg_a, version, "reviewer_a")
        assert svc.release_version(version)["ok"]

        # 同任务的后续版本提高阈值，不影响已交付版本自己的阈值与签名。
        version_row = TranscriptVersionService().resolve_version(version)
        TranscriptVersionService().create_version(
            f"TRSV-{uuid.uuid4().hex[:8]}", version_row["关联任务"], "v2", "v1", 1, "后续版本", 0.80,
        )
        delivered = svc.build_release_review(version)
        assert delivered["threshold"] == pytest.approx(0.70)
        assert delivered["delivered"] is True
        assert delivered["signed_count"] == 1
        assert delivered["segments"][0]["signature_valid"]


class TestReviewerTodo:
    def test_claim_from_todo_is_idempotent(self):
        seg_a = f"SEG-{uuid.uuid4().hex[:6]}"
        _, version = _seed_task([(seg_a, 0.62)], 0.80)
        svc = ConfidenceReviewService()

        first = svc.claim_segment(seg_a, version, "reviewer_a")
        assert first["ok"]
        assert first["review_id"]
        again = svc.claim_segment(seg_a, version, "reviewer_a")
        assert not again["ok"]
        assert "待其签名" in again["message"]

    def test_other_reviewer_cannot_sign_claimed_segment(self):
        seg_a = f"SEG-{uuid.uuid4().hex[:6]}"
        _, version = _seed_task([(seg_a, 0.62)], 0.80)
        svc = ConfidenceReviewService()

        assert svc.claim_segment(seg_a, version, "reviewer_a")["ok"]
        result = svc.submit_signature(seg_a, version, "reviewer_b")
        assert not result["ok"]
        assert "reviewer_a" in result["message"]
        assert svc.build_release_review(version)["signed_count"] == 0

    def test_reclaim_takes_new_threshold(self):
        seg_a = f"SEG-{uuid.uuid4().hex[:6]}"
        _, version = _seed_task([(seg_a, 0.62)], 0.70)
        svc = ConfidenceReviewService()
        svc.claim_segment(seg_a, version, "reviewer_a")
        TranscriptVersionService().set_threshold(version, 0.80)

        reclaim = svc.claim_segment(seg_a, version, "reviewer_a")
        assert reclaim["ok"]
        assert reclaim["threshold"] == pytest.approx(0.80)
        signed = svc.submit_signature(seg_a, version, "reviewer_a")
        assert signed["signature_valid"] and signed["counted"]


class TestSeedScenario:
    """种子数据对应制作人发布 V2 与两份回执相遇的现场。"""

    def test_seed_v2_reports_stale_claim_and_valid_neighbor(self):
        svc = ConfidenceReviewService()
        detail = svc.build_release_review("v2")
        assert detail["threshold"] == pytest.approx(0.80)
        assert detail["threshold_changed"]
        assert detail["previous_threshold"] == pytest.approx(0.70)

        by_segment = {item["segment_id"]: item for item in detail["segments"]}
        # 0.62 段按旧口径领取、签名迟到，必须判为无效并指回 reviewer_01 重审。
        assert by_segment["SPCH-0001"]["open_claim"]["claimant"] == "reviewer_01"
        assert by_segment["SPCH-0001"]["needs_review_by"] == "reviewer_01"
        # 0.91 段在 0.80 阈值下不再需要签名。
        assert by_segment["SPCH-0003"]["exempt"]

        late = svc.submit_signature("SPCH-0001", "v2", "reviewer_01")
        assert not late["signature_valid"]
        detail = svc.build_release_review("v2")
        assert "reviewer_01" in detail["message"]
        assert "重审" in detail["message"]
        assert "SPCH-0001" in detail["missing_segments"]

    def test_seed_v1_keeps_its_threshold_and_signature(self):
        svc = ConfidenceReviewService()
        detail = svc.build_release_review("v1")
        assert detail["threshold"] == pytest.approx(0.70)
        assert detail["delivered"] is True
        assert detail["ok"]
        signature = detail["segments"][0]["valid_signature"]
        assert signature["threshold_text"] == "0.70"
