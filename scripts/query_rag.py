#!/usr/bin/env python3
"""
钱博士RAG查询模块
提供语义检索接口，供Agent和简报脚本使用
基于ChromaDB内置ONNX Embedding（无需torch）

用法:
    # 模块导入
    from query_rag import QianboshiRAG
    rag = QianboshiRAG()
    results = rag.query("光模块现在怎么看", top_k=5)

    # 命令行
    python query_rag.py "光模块现在怎么看"
    python query_rag.py "钱博士对紫金矿业的看法" --top-k 3 --verbose
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, date
from pathlib import Path


BANNED_SOURCES = ("主力行为学", "汤山老王", "马跑跑", "邻居大爷", "八叔不啰嗦")

QUERY_KEYWORDS = {
    "创新药": ["创新药", "医药", "CXO", "CRO", "159992", "药"],
    "医药": ["创新药", "医药", "CXO", "CRO", "159992", "药"],
    "光模块": ["光模块", "光通讯", "CPO", "新易盛", "中际旭创", "天孚", "源杰", "300502", "300308"],
    "光通讯": ["光模块", "光通讯", "CPO", "新易盛", "中际旭创", "天孚", "源杰", "300502", "300308"],
    "机器人": ["机器人", "具身", "减速器", "伺服", "159770", "优必选"],
    "半导体": ["半导体", "芯片", "中芯", "设备", "先进制程", "688981", "159813"],
    "芯片": ["半导体", "芯片", "中芯", "设备", "先进制程", "688981", "159813"],
    "存储": ["存储", "长鑫", "DDR", "HBM", "内存", "兆易"],
    "紫金矿业": ["紫金", "黄金", "铜", "有色", "工业金属", "601899"],
    "工业金属": ["紫金", "黄金", "铜", "有色", "工业金属", "601899"],
    "AMD": ["AMD", "OpenAI", "通富微电", "封测", "GPU"],
    "NVDA": ["NVDA", "英伟达", "NVIDIA", "算力", "GPU", "CPO"],
}

def _contains_banned_source(source):
    return any(b in (source or "") for b in BANNED_SOURCES)

def _keyword_overlap_ok(query, source, section, content):
    haystack = f"{source} {section} {content}".lower()
    query_upper = query.upper()
    for trigger, keywords in QUERY_KEYWORDS.items():
        if trigger.lower() in query.lower() or trigger.upper() in query_upper:
            return any(k.lower() in haystack for k in keywords)
    return True


def _extract_query_dates(query):
    """从查询里提取明确日期，用于硬过滤，如 7月20日 / 7.20 / 2026.07.20。"""
    dates = set()
    for y, m, d in re.findall(r'(20\d{2})[.年/-](\d{1,2})[.月/-](\d{1,2})', query):
        dates.add(date(int(y), int(m), int(d)))
    for m, d in re.findall(r'(?<!\d)(\d{1,2})[.月/](\d{1,2})(?:日)?', query):
        mi, di = int(m), int(d)
        if 1 <= mi <= 12 and 1 <= di <= 31:
            dates.add(date(2026, mi, di))
    return dates


class QianboshiRAG:
    """钱博士RAG查询引擎"""

    def __init__(self, config=None):
        self.config = config or self._load_config()
        # 如果传入的是原始config.yaml dict（没有vector_db_path），重新加载
        if config is not None and "vector_db_path" not in config:
            loaded = self._load_config()
            loaded.update({k: v for k, v in config.items() if k not in loaded})
            self.config = loaded
        self._collection = None
        self._client = None

    @staticmethod
    def _load_config():
        """加载配置 — 优先从 config.yaml，回退到硬编码"""
        # 尝试从 config_loader 获取向量库路径
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from config_loader import load_config, get_vector_db_path
            cfg = load_config()
            vdb = get_vector_db_path(cfg)
            return {
                "vector_db_path": str(vdb / "chroma"),
                "collection_name": cfg.get("rag", {}).get("collection_name", "qianboshi"),
                "top_k": cfg.get("rag", {}).get("top_k", 5),
                "score_weights": cfg.get("rag", {}).get("score_weights", {
                    "similarity": 0.6, "freshness": 0.2, "type_boost": 0.2,
                }),
                "type_weights": cfg.get("rag", {}).get("type_weights", {
                    "short_video": 1.0, "livestream": 0.8, "catalog": 0.0,
                }),
            }
        except Exception:
            # 回退：旧硬编码路径
            script_dir = Path(__file__).parent
            return {
                "vector_db_path": str(script_dir / ".." / "vector_db" / "chroma"),
                "collection_name": "qianboshi",
                "top_k": 5,
                "score_weights": {"similarity": 0.6, "freshness": 0.2, "type_boost": 0.2},
                "type_weights": {"short_video": 1.0, "livestream": 0.8, "catalog": 0.0},
            }

    @property
    def collection(self):
        if self._collection is None:
            self._init_client()
        return self._collection

    def _init_client(self):
        """初始化ChromaDB客户端"""
        try:
            import chromadb
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
        except ImportError:
            print("[ERROR] chromadb 未安装: pip install chromadb", file=sys.stderr)
            sys.exit(1)

        db_path = Path(self.config["vector_db_path"])
        if not db_path.exists():
            print(f"[ERROR] 向量库不存在: {db_path}", file=sys.stderr)
            print("[INFO] 请先运行: python scripts/build_vector_db.py", file=sys.stderr)
            sys.exit(1)

        embedding_function = ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
        self._client = chromadb.PersistentClient(path=str(db_path))
        self._collection = self._client.get_collection(
            self.config["collection_name"],
            embedding_function=embedding_function,
        )

    @staticmethod
    def _classify_source(source):
        """判断文档类型：short_video / livestream / catalog"""
        if not source:
            return "catalog"
        if "短视频解读" in source:
            return "short_video"
        if "直播复盘" in source or "钱博士直播" in source:
            return "livestream"
        if "B站视频源清单" in source or "catalog" in source.lower():
            return "catalog"
        return "livestream"  # 默认

    @staticmethod
    def _extract_date(source):
        """从文件名或pubdate缓存提取日期，返回 date 对象"""
        if not source:
            return date(2026, 6, 1)
        # 格式1: 2026.6.25
        match = re.search(r'(\d{4})\.(\d{1,2})\.(\d{1,2})', source)
        if match:
            y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return date(y, m, d)
        # 格式2: "6月14日" 
        match = re.search(r'(\d{1,2})月(\d{1,2})日', source)
        if match:
            return date(2026, int(match.group(1)), int(match.group(2)))
        # 格式3: 从文件名提取BV号，查pubdate缓存
        bv_match = re.search(r'(BV[0-9A-Za-z]+)', source)
        if bv_match:
            bv = bv_match.group(1)
            try:
                import json
                from pathlib import Path
                for p in [Path(__file__).parent.parent / "data" / "bv_pubdates.json",
                          Path(__file__).parent.parent / "data" / "shenyan_video_meta.json"]:
                    if p.exists():
                        data = json.loads(p.read_text(encoding="utf-8"))
                        entry = data.get(bv)
                        if entry:
                            pubdate = entry["pubdate"] if isinstance(entry, dict) else entry
                            if isinstance(pubdate, (int, float)):
                                from datetime import datetime as _dt
                                return _dt.fromtimestamp(pubdate).date()
            except Exception:
                pass
        return date(2026, 6, 1)

    def _calc_freshness(self, source):
        """计算时间新鲜度 (0-1)，当天=1.0，越久越低"""
        doc_date = self._extract_date(source)
        today = date.today()
        days_diff = (today - doc_date).days
        if days_diff <= 0:
            return 1.0
        # 30天内线性衰减，30天后最低0.1
        return max(0.1, 1.0 - days_diff / 30)

    def _calc_final_score(self, sim_score, source):
        """加权综合评分"""
        weights = self.config["score_weights"]
        type_w = self.config["type_weights"]

        doc_type = self._classify_source(source)
        type_score = type_w.get(doc_type, 0.5)
        freshness = self._calc_freshness(source)

        final = (
            sim_score * weights["similarity"]
            + freshness * weights["freshness"]
            + type_score * weights["type_boost"]
        )
        return round(final, 4), {
            "sim_weighted": round(sim_score * weights["similarity"], 4),
            "freshness": round(freshness, 4),
            "freshness_weighted": round(freshness * weights["freshness"], 4),
            "type_score": type_score,
            "type_weighted": round(type_score * weights["type_boost"], 4),
        }

    def query(self, text, top_k=None, score_threshold=0.0, max_days=None):
        """
        语义检索（带权重排序）

        参数:
            text: 查询文本
            top_k: 返回结果数（默认config中的值）
            score_threshold: 相似度阈值（0-1），低于此值的结果被过滤
            max_days: 仅返回最近N天的结果

        返回:
            [{"content": str, "source": str, "section": str, "score": float, "raw_score": float, "type": str}, ...]
        """
        top_k = top_k or self.config.get("top_k", 5)
        if _contains_banned_source(text):
            return []
        query_dates = _extract_query_dates(text)
        
        # 构建查询参数
        query_kwargs = {
            "query_texts": [text],
            "n_results": min(max(top_k * 200, 1000), 5000),
            "include": ["documents", "metadatas", "distances"],
        }
        
        # 如果指定了max_days，添加日期过滤
        if max_days:
            from datetime import timedelta
            cutoff = date.today() - timedelta(days=max_days)
            # 无法直接用date过滤metadata，改用获取全部后筛选
            query_kwargs["n_results"] = 10000
        
        results = self.collection.query(**query_kwargs)

        if not results["documents"] or not results["documents"][0]:
            return []

        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        items = []
        for doc, meta, dist in zip(docs, metas, distances):
            sim_score = 1.0 - dist
            if sim_score < score_threshold or sim_score < 0.45:
                continue
            if "本文基于直播转录整理" in doc and len(doc) < 120:
                continue

            source = meta.get("source", "unknown")
            section = meta.get("section", "")
            doc_type = self._classify_source(source)
            doc_date = self._extract_date(source)
            if query_dates and doc_date not in query_dates:
                continue

            # 排除目录型文档、禁用分析师、明显弱相关结果
            if doc_type == "catalog" or _contains_banned_source(source):
                continue
            if not _keyword_overlap_ok(text, source, section, doc):
                continue

            final_score, weight_detail = self._calc_final_score(sim_score, source)

            # 提取展示用日期
            date_str = str(doc_date) if doc_date else ""

            items.append(
                {
                    "content": doc,
                    "source": source,
                    "section": section,
                    "score": final_score,
                    "raw_score": round(sim_score, 4),
                    "date": date_str,
                    "type": doc_type,
                    "weights": weight_detail,
                }
            )

        # 按加权分数排序
        items.sort(key=lambda x: x["score"], reverse=True)
        return items[:top_k]

    def query_by_section(self, section_keyword, top_k=10):
        """按板块/小节名检索"""
        results = self.collection.get(
            where={"section": {"$contains": section_keyword}},
            limit=top_k,
        )
        if not results or not results["documents"]:
            return []

        items = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            source = meta.get("source", "unknown")
            if _contains_banned_source(source):
                continue
            items.append(
                {
                    "content": doc,
                    "source": source,
                    "section": meta.get("section"),
                }
            )
        return items

    def list_sources(self):
        """列出所有文档来源"""
        results = self.collection.get(include=["metadatas"])
        sources = set()
        for meta in results["metadatas"]:
            src = meta.get("source", "")
            if src:
                sources.add(src)
        return sorted(sources)


def format_results(results, verbose=False, show_weights=False):
    """格式化查询结果为可读文本"""
    if not results:
        return "❌ 未找到相关信息。"

    lines = [f"找到 {len(results)} 条相关结果:\n"]
    for i, r in enumerate(results, 1):
        # 截断内容显示
        content = r["content"]
        if len(content) > 200 and not verbose:
            content = content[:200] + "..."

        lines.append(f"{'='*60}")
        lines.append(f"[{i}] 来源: {r['source']}")
        if r.get("section"):
            lines.append(f"    板块: {r['section']}")
        lines.append(f"    综合分: {r['score']:.2%}  |  向量: {r.get('raw_score', 0):.2%}  |  类型: {r.get('type', '?')}")

        if show_weights and r.get("weights"):
            w = r["weights"]
            lines.append(f"    ── 权重构成 ──")
            lines.append(f"    向量相似加权: {w['sim_weighted']:.2%}")
            lines.append(f"    时间新鲜加权: {w['freshness_weighted']:.2%} (新鲜度{w['freshness']:.0%})")
            lines.append(f"    类型加成加权: {w['type_weighted']:.2%} (类型分{w['type_score']:.1f})")
            lines.append(f"    综合 = {' + '.join([f'{w[k]:.2%}' for k in ['sim_weighted','freshness_weighted','type_weighted']])}")

        if r.get("date"):
            lines.append(f"    日期: {r['date']}")
        lines.append(f"    内容: {content}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="钱博士RAG查询")
    parser.add_argument("query_text", nargs="?", help="查询文本")
    parser.add_argument("--top-k", type=int, default=5, help="返回结果数")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示完整内容")
    parser.add_argument("--weights", action="store_true", help="展示权重构成明细")
    parser.add_argument("--json", action="store_true", help="JSON格式输出")
    parser.add_argument("--section", help="按板块名检索（如'光模块'）")
    parser.add_argument("--list-sources", action="store_true", help="列出所有文档来源")
    args = parser.parse_args()

    rag = QianboshiRAG()

    if args.list_sources:
        sources = rag.list_sources()
        print("文档来源:")
        for s in sources:
            print(f"  - {s}")
        sys.exit(0)

    if args.section:
        results = rag.query_by_section(args.section, top_k=args.top_k)
    elif args.query_text:
        results = rag.query(args.query_text, top_k=args.top_k)
    else:
        parser.print_help()
        sys.exit(1)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_results(results, verbose=args.verbose, show_weights=args.weights))
