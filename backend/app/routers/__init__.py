"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。

固定路径的发布复核路由必须先于通用 /api/{module}/{entry_id} 注册，
否则 /api/confidence_review/todo 会被动态段抢先匹配。
"""
from __future__ import annotations

from app.routers import release_review, resource

ROUTERS = [release_review, resource]
