"""
配置管理
统一从项目根目录的 .env 文件加载配置
"""

import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


class Config:
    """Flask配置类"""

    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'

    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False

    # ===== LLM 配置 =====
    # 多 provider 支持（runtime switch via /api/settings/llm-provider）
    # 每个 provider 有独立 API key；激活的 provider 写在状态文件中。
    MINIMAX_API_KEY = os.environ.get('MINIMAX_API_KEY')
    KIMI_API_KEY = os.environ.get('KIMI_API_KEY')

    # 启动时的默认 provider（仅在状态文件不存在时使用）
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'minimax')

    # 向后兼容：custom provider 走这三个变量
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')

    # ===== 记忆后端配置 =====
    # MEMORY_BACKEND: "graphiti"（本地 Neo4j）或 "zep"（Zep Cloud 兜底）
    MEMORY_BACKEND = os.environ.get('MEMORY_BACKEND', 'graphiti').lower()

    # Zep Cloud（仅在 MEMORY_BACKEND=zep 时需要）
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')

    # Graphiti / Neo4j（本地）
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'mirofish-neo4j')

    # 本地嵌入 / 重排序模型（CPU 友好）
    EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'BAAI/bge-small-en-v1.5')
    RERANKER_MODEL = os.environ.get('RERANKER_MODEL', 'BAAI/bge-reranker-base')

    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小

    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_MAX_RUNTIME_SECONDS = int(os.environ.get('OASIS_MAX_RUNTIME_SECONDS', '3600'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]

    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def validate(cls):
        """验证必要配置。仅校验当前激活 provider 的 key 和当前 memory 后端的依赖。"""
        errors = []

        # LLM: 至少一个 provider 已配置
        from .utils import llm_providers
        active = llm_providers.get_active_provider()
        if not os.environ.get(active.api_key_env):
            errors.append(
                f"当前激活 provider '{active.name}' 的 API key ({active.api_key_env}) 未配置"
            )

        # Memory backend
        if cls.MEMORY_BACKEND == 'zep':
            if not cls.ZEP_API_KEY:
                errors.append("MEMORY_BACKEND=zep 但 ZEP_API_KEY 未配置")
        elif cls.MEMORY_BACKEND == 'graphiti':
            # Neo4j 必须可达（这里只校验配置非空，连接性在启动时校验）
            if not cls.NEO4J_URI or not cls.NEO4J_USER or not cls.NEO4J_PASSWORD:
                errors.append("MEMORY_BACKEND=graphiti 但 NEO4J_URI/USER/PASSWORD 未完整配置")
        else:
            errors.append(f"未知的 MEMORY_BACKEND: {cls.MEMORY_BACKEND}（支持 graphiti / zep）")

        return errors
