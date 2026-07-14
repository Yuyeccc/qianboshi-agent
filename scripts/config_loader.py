#!/usr/bin/env python3
"""
钱博士Agent — 统一配置加载器

所有脚本通过此模块加载配置，避免硬编码路径。
优先级: 代码默认值 < config.yaml < 环境变量 < 命令行参数

用法:
    from config_loader import load_config, get_data_path

    config = load_config()                     # 自动寻找 config.yaml
    config = load_config("custom/path.yaml")   # 指定路径
    data_dir = get_data_path(config)           # 取数据目录绝对路径
"""
import os
import sys
from pathlib import Path


def _find_config():
    """自动查找 config.yaml，按优先级:
    1. 环境变量 QIANBOSHI_CONFIG
    2. 当前目录 ./config.yaml
    3. 脚本同目录 ./config.yaml
    4. 项目根目录 config.yaml
    """
    # 环境变量最高优先级
    env_path = os.environ.get("QIANBOSHI_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # 尝试各候选位置
    candidates = [
        Path.cwd() / "config.yaml",
        Path(__file__).parent / "config.yaml",
        Path(__file__).parent.parent / "config.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p

    return None


def _load_dotenv():
    """加载项目根目录的 .env 文件到 os.environ。
    只在变量不存在时设置（不覆盖已有的环境变量）。
    """
    env_path = os.environ.get("QIANBOSHI_ENV")
    if not env_path:
        # 和 config.yaml 同目录查找 .env
        cfg = _find_config()
        if cfg:
            env_path = cfg.parent / ".env"
        else:
            env_path = Path.cwd() / ".env"
    else:
        env_path = Path(env_path)

    if not env_path.exists():
        return

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                # 不覆盖已有环境变量
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass  # .env 加载失败不影响主流程


def get_api_key(config):
    """获取 API 密钥。优先级：环境变量 > .env文件 > config.yaml 中的 api_key_env 指向的环境变量"""
    _load_dotenv()  # 确保 .env 已加载

    # 直接检查 DEEPSEEK_API_KEY 环境变量
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key

    # 检查 config.yaml 中指定的环境变量名
    if config:
        key_env = config.get("llm", {}).get("api_key_env", "")
        if key_env:
            return os.environ.get(key_env, "")

    return ""


def get_llm_config(config):
    """获取 LLM 完整配置"""
    _load_dotenv()
    llm = config.get("llm", {}) if config else {}
    return {
        "api_key": get_api_key(config),
        "api_base": llm.get("api_base", "https://api.deepseek.com/v1"),
        "routine_model": llm.get("routine_model", "deepseek-chat"),
        "analysis_model": llm.get("analysis_model", "deepseek-v4-pro"),
        "max_tokens": llm.get("max_tokens", 4096),
        "temperature_routine": llm.get("temperature", {}).get("routine", 0.3),
        "temperature_analysis": llm.get("temperature", {}).get("analysis", 0.7),
    }


def load_config(config_path=None):
    """
    加载配置，返回 dict。
    未找到 config.yaml 时返回空 dict（脚本用自己的硬编码默认值回退）。
    """
    if config_path:
        p = Path(config_path)
    else:
        p = _find_config()

    if p is None or not p.exists():
        return {}

    try:
        import yaml
        with open(p, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        if cfg is None:
            return {}
        return cfg
    except ImportError:
        print("[WARN] PyYAML 未安装，跳过 config.yaml (pip install PyYAML)",
              file=sys.stderr)
        return {}
    except Exception as e:
        print(f"[WARN] 读取 config.yaml 失败: {e}", file=sys.stderr)
        return {}


def get_data_dir(config):
    """
    从配置获取数据目录的绝对路径。
    如果 config.yaml 中没有配置，回退到 skill 目录同级。
    """
    # 环境变量覆盖
    env_dir = os.environ.get("QIANBOSHI_DATA_DIR")
    if env_dir:
        return Path(env_dir).resolve()

    # config.yaml
    paths = config.get("paths", {})
    data_rel = paths.get("data_dir", "")
    if data_rel:
        # 如果是绝对路径，直接返回
        if os.path.isabs(data_rel):
            return Path(data_rel).resolve()
        # 相对路径：相对于 config.yaml 所在目录或当前目录
        cfg_path = _find_config()
        if cfg_path:
            return (cfg_path.parent / data_rel).resolve()
        return (Path.cwd() / data_rel).resolve()

    # 传统回退：skill 目录下
    return Path(__file__).parent.parent.resolve()


def get_obsidian_path(config):
    """获取 Obsidian 笔记目录路径"""
    # 环境变量
    env_path = os.environ.get("QIANBOSHI_OBSIDIAN_PATH")
    if env_path:
        return Path(env_path).resolve()

    # config.yaml
    obsidian = config.get("paths", {}).get("obsidian_vault", "")
    if obsidian:
        return Path(obsidian).resolve()

    # 默认
    return Path("E:/obsidian-vault/学习/钱博士")


def get_vector_db_path(config):
    """获取向量库路径"""
    # 环境变量
    env_path = os.environ.get("QIANBOSHI_VECTOR_DB_PATH")
    if env_path:
        return Path(env_path).resolve()

    # config.yaml
    db_rel = config.get("rag", {}).get("vector_db_path", "")
    if db_rel:
        if os.path.isabs(db_rel):
            return Path(db_rel).resolve()
        cfg_path = _find_config()
        if cfg_path:
            return (cfg_path.parent / db_rel).resolve()
        return (Path.cwd() / db_rel).resolve()

    # 默认：data_dir/vector_db
    return get_data_dir(config) / "vector_db"


def get_proxy(config):
    """获取代理地址"""
    proxy = config.get("market", {}).get("proxy", "")
    if proxy:
        return proxy
    return os.environ.get("HTTP_PROXY", "")


if __name__ == "__main__":
    # 测试：打印当前配置
    cfg = load_config()
    print("=== 配置测试 ===")
    print(f"config.yaml: {_find_config()}")
    print(f"data_dir: {get_data_dir(cfg)}")
    print(f"obsidian_path: {get_obsidian_path(cfg)}")
    print(f"vector_db_path: {get_vector_db_path(cfg)}")
    print(f"proxy: {get_proxy(cfg)}")
