"""发布复核接口：制作人发布前的覆盖校验明细、发布放行，以及复核员的待办、领取与签名回执。

路径固定写在通用 /api/{module}/{entry_id} 之前注册，避免被动态段抢占。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas import ActionResult
from app.services.confidence_review import ConfidenceReviewService
from app.services.transcript_version import TranscriptVersionService

router = APIRouter(prefix="/api", tags=["发布复核"])

_review = ConfidenceReviewService()
_versions = TranscriptVersionService()


class ClaimPayload(BaseModel):
    segment_id: str
    version: str
    reviewer: str


class SignaturePayload(BaseModel):
    segment_id: str
    version: str
    reviewer: str
    conclusion: str = Field(default="通过")


class PublishPayload(BaseModel):
    actor: str = Field(default="制作人")


def _require_version(version_ref: str) -> None:
    if _versions.resolve_version(version_ref) is None:
        raise HTTPException(status_code=404, detail=f"版本 {version_ref} 不存在")


@router.get("/transcript_version/{version_ref}/release-review", response_model=dict)
def release_review(version_ref: str) -> dict[str, Any]:
    """服务端发布复核明细：按该版本生效阈值核对低置信段与签名。"""
    _require_version(version_ref)
    return _review.build_release_review(version_ref)


@router.post("/transcript_version/{version_ref}/release", response_model=dict)
def release_version(version_ref: str, payload: PublishPayload | None = None) -> dict[str, Any]:
    """制作人点发布：覆盖不完整时返回明细并阻断，完整时放行版本生效。"""
    _require_version(version_ref)
    actor = payload.actor if payload else "制作人"
    return _review.release_version(version_ref, actor)


@router.get("/confidence_review/todo", response_model=dict)
def review_todo(version: str = Query(...)) -> dict[str, Any]:
    """复核员待办：每个需签名段的签名有效性、领取人与重审责任。"""
    _require_version(version)
    return _review.build_todo(version)


@router.post("/confidence_review/claim", response_model=dict)
def claim_segment(payload: ClaimPayload) -> dict[str, Any]:
    """复核员从待办领取仍缺有效签名的段。"""
    _require_version(payload.version)
    return _review.claim_segment(payload.segment_id, payload.version, payload.reviewer)


@router.post("/confidence_review/signature", response_model=dict)
def submit_signature(payload: SignaturePayload) -> dict[str, Any]:
    """提交段签名：签名绑定该段与该版本，旧阈值签署的迟到签名记为无效。"""
    _require_version(payload.version)
    return _review.submit_signature(
        payload.segment_id, payload.version, payload.reviewer, payload.conclusion,
    )


@router.post("/confidence_review/{review_id}/sign", response_model=ActionResult)
def sign_existing_review(review_id: str, payload: SignaturePayload) -> ActionResult:
    """按复核编号补签：先解析该条目绑定的段与版本再走同一条签名链路。"""
    rows = [r for r in _review.get_reviews_by_segment(payload.segment_id)
            if str(r.get("复核编号")) == review_id]
    if not rows:
        raise HTTPException(status_code=404, detail=f"复核条目 {review_id} 不存在")
    row = rows[0]
    result = _review.submit_signature(
        str(row.get("关联分段")), payload.version, payload.reviewer, payload.conclusion,
    )
    return ActionResult(ok=bool(result.get("ok")), message=str(result.get("message", "")))
