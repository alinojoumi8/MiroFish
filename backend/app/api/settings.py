"""
运行时设置 API: LLM provider 切换。
"""

from flask import jsonify, request

from . import settings_bp
from ..utils import llm_providers


@settings_bp.route('/llm-provider', methods=['GET'])
def get_llm_provider():
    """返回所有 provider 及当前激活状态。"""
    active = llm_providers.get_active_provider()
    return jsonify({
        "active": {
            "name": active.name,
            "label": active.label,
            "model": llm_providers.get_active_model(),
            "base_url": llm_providers.get_active_base_url(),
        },
        "available": llm_providers.list_providers(),
    })


@settings_bp.route('/llm-provider', methods=['POST'])
def set_llm_provider():
    """切换激活的 provider。Body: {"provider": "minimax"|"kimi"|"custom", "model"?: "..."}"""
    data = request.get_json(silent=True) or {}
    name = data.get('provider')
    model_override = data.get('model')

    if not name:
        return jsonify({"error": "missing 'provider' in body"}), 400

    try:
        profile = llm_providers.set_active_provider(name, model_override)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "ok": True,
        "active": {
            "name": profile.name,
            "label": profile.label,
            "model": llm_providers.get_active_model(),
            "base_url": llm_providers.get_active_base_url(),
        },
    })
