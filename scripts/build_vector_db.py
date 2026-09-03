#!/usr/bin/env python3
"""
钱博士RAG向量库构建脚本 — 支持增量upsert

用法:
    python build_vector_db.py                     # 首次构建（全量）
    python build_vector_db.py --rebuild           # 重建（删除旧库后全量重建）
    python build_vector_db.py --upsert xxx.md     # 增量添加/更新单篇笔记
    python build_vector_db.py --remove xxx.md     # 删除单篇笔记
    python build_vector_db.py --scan              # 自动检测新增/修改的文件并upsert
"""
import argparse
import hashlib
import json
import os
import re
import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config as load_yaml_config

DEFAULT_CONFIG = {
    "obsidian_path": "E:/obsidian-vault/学习/钱博士",
    "notes_dir": "",
    "vector_db_path": "",
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "chunk_size": 500,
    "chunk_overlap": 50,
    "collection_name": "qianboshi",
}


def load_config(config_path=None):
    """加载配置，合并config.yaml + 环境变量"""
    config = DEFAULT_CONFIG.copy()
    yaml_cfg = load_yaml_config(config_path) or {}

    if "paths" in yaml_cfg:
        p = yaml_cfg["paths"]
        if p.get("obsidian_vault"):
            config["obsidian_path"] = p["obsidian_vault"]
        if p.get("notes_dir"):
            config["notes_dir"] = p["notes_dir"]
        if p.get("data_dir"):
            config["vector_db_path"] = str(Path(p["data_dir"]) / "vector_db")

    if "rag" in yaml_cfg:
        r = yaml_cfg["rag"]
        if r.get("vector_db_path"):
            config["vector_db_path"] = r["vector_db_path"]
        if r.get("collection_name"):
            config["collection_name"] = r["collection_name"]

    # 环境变量覆盖
    if os.environ.get("QIANBOSHI_OBSIDIAN_PATH"):
        config["obsidian_path"] = os.environ["QIANBOSHI_OBSIDIAN_PATH"]
    if os.environ.get("QIANBOSHI_VECTOR_DB_PATH"):
        config["vector_db_path"] = os.environ["QIANBOSHI_VECTOR_DB_PATH"]

    return config


def _resolve_vector_db(config):
    """解析向量库路径"""
    vp = config.get("vector_db_path", "")
    if vp:
        return Path(vp)
    return Path("data/vector_db")


# ─── 笔记扫描 ─────────────────────────────────────────────

def find_notes(obsidian_path, notes_dir=None):
    """扫描笔记目录，返回Path列表"""
    notes = []
    obs = Path(obsidian_path)
    if obs.exists():
        notes.extend(sorted(obs.glob("*.md")))
        print(f"[INFO] Obsidian '{obsidian_path}': {len(notes)} 篇笔记")
    else:
        print(f"[WARN] Obsidian路径不存在: {obs.resolve()}")

    if notes_dir:
        nd = Path(notes_dir)
        if nd.exists():
            extra = sorted(nd.rglob("*.md"))
            seen = set()
            deduped = []
            for fn in extra:
                if fn.name not in seen:
                    seen.add(fn.name)
                    deduped.append(fn)
            obs_names = set(n.name for n in notes)
            new = [n for n in deduped if n.name not in obs_names]
            notes.extend(new)
            print(f"[INFO] notes_dir '{notes_dir}': {len(extra)}→{len(deduped)}去重, +{len(new)}")
        else:
            print(f"[WARN] notes_dir不存在: {nd.resolve()}")

    return notes


def resolve_note_path(filename, config):
    """根据文件名查找笔记的完整路径。
    先在 obsidian_path 找，再在 notes_dir 递归找。
    """
    obs = Path(config["obsidian_path"])
    candidate = obs / filename
    if candidate.exists():
        return candidate

    nd = config.get("notes_dir", "")
    if nd:
        for f in Path(nd).rglob(filename):
            return f

    return None


# ─── 文本分块 ─────────────────────────────────────────────

def strip_frontmatter(text):
    if text.startswith("---"):
        idx = text.find("---", 3)
        if idx != -1:
            return text[idx + 3:]
    return text


def chunk_markdown(text, source, chunk_size=500, chunk_overlap=50):
    """按标题+段落分块。返回 [{\"content\":..., \"source\":..., \"section\":..., \"chunk_id\":...}]"""
    text = strip_frontmatter(text)
    sections = re.split(r"(?=^##\s)", text, flags=re.MULTILINE)
    chunks = []

    for section in sections:
        section = section.strip()
        if not section or len(section) < 20:
            continue
        title_match = re.match(r"^#+\s+(.*)", section)
        section_title = title_match.group(1) if title_match else ""
        paragraphs = re.split(r"\n\n+", section)

        current_chunk = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(current_chunk) + len(para) > chunk_size and current_chunk:
                chunks.append({
                    "content": current_chunk.strip(),
                    "source": source,
                    "section": section_title,
                    "chunk_id": len(chunks),
                })
                words = current_chunk.split()
                overlap_text = " ".join(words[-chunk_overlap:]) if len(words) > chunk_overlap else ""
                current_chunk = overlap_text + "\n\n" + para if overlap_text else para
            else:
                current_chunk = current_chunk + "\n\n" + para if current_chunk else para

        if current_chunk.strip():
            chunks.append({
                "content": current_chunk.strip(),
                "source": source,
                "section": section_title,
                "chunk_id": len(chunks),
            })
    return chunks


def make_chunk_id(source, chunk_id):
    """生成确定性chunk ID（同source+chunk_id永远得到相同ID）"""
    return hashlib.md5(f"{source}#{chunk_id}".encode()).hexdigest()[:16]


# ─── 索引管理 ─────────────────────────────────────────────

class ChunkIndex:
    """管理 source→chunk_ids 映射，持久化到 index.json"""

    def __init__(self, vector_db_path):
        self.path = Path(vector_db_path) / "index.json"
        self.data = {}  # {filename: {"chunk_ids": [...], "mtime": float, "sha256": str}}

    def load(self):
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        return self

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, filename):
        return self.data.get(filename, {})

    def set(self, filename, chunk_ids, file_path=None):
        entry = {"chunk_ids": chunk_ids}
        if file_path:
            p = Path(file_path)
            entry["mtime"] = p.stat().st_mtime
            entry["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        self.data[filename] = entry

    def remove(self, filename):
        return self.data.pop(filename, None)

    def filenames(self):
        return list(self.data.keys())


# ─── ChromaDB 操作 ────────────────────────────────────────

def _get_or_create_collection(config, vector_db_path):
    """获取或创建ChromaDB collection"""
    import chromadb
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

    chroma_path = vector_db_path / "chroma"
    chroma_path.mkdir(parents=True, exist_ok=True)

    ef = ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
    client = chromadb.PersistentClient(path=str(chroma_path))
    coll_name = config["collection_name"]

    # Try get existing, else create
    try:
        collection = client.get_collection(coll_name, embedding_function=ef)
        print(f"[INFO] 使用已有collection: {coll_name}")
    except Exception:
        collection = client.create_collection(
            name=coll_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        print(f"[INFO] 创建新collection: {coll_name}")

    return collection


def _delete_collection(config, vector_db_path):
    """删除旧collection"""
    import chromadb

    chroma_path = vector_db_path / "chroma"
    if not chroma_path.exists():
        return
    try:
        client = chromadb.PersistentClient(path=str(chroma_path))
        client.delete_collection(config["collection_name"])
        print(f"[INFO] 已删除collection: {config['collection_name']}")
    except Exception:
        pass


# ─── 核心操作 ─────────────────────────────────────────────

def upsert_note(filename, config, verbose=True):
    """增量添加/更新单篇笔记到向量库"""
    file_path = resolve_note_path(filename, config)
    if file_path is None:
        print(f"[ERROR] 找不到笔记文件: {filename}")
        return False

    vector_db_path = _resolve_vector_db(config)
    collection = _get_or_create_collection(config, vector_db_path)
    index = ChunkIndex(vector_db_path).load()

    if verbose:
        print(f"[UPSERT] {filename} ← {file_path}")

    # 1. 如果已索引过，先删除旧chunks
    old_entry = index.get(filename)
    if old_entry and old_entry.get("chunk_ids"):
        old_ids = old_entry["chunk_ids"]
        try:
            collection.delete(ids=old_ids)
            if verbose:
                print(f"  删除旧chunks: {len(old_ids)} 条")
        except Exception as e:
            print(f"  [WARN] 删除旧chunks失败: {e}")

    # 2. 分块
    text = file_path.read_text(encoding="utf-8")
    chunks = chunk_markdown(
        text, filename,
        config["chunk_size"], config["chunk_overlap"]
    )

    if not chunks:
        print(f"  [WARN] 文件无有效内容")
        return False

    # 3. 写入新chunks
    ids = []
    docs = []
    metas = []
    for c in chunks:
        cid = make_chunk_id(c["source"], c["chunk_id"])
        ids.append(cid)
        docs.append(c["content"])
        metas.append({"source": c["source"], "section": c["section"], "chunk_id": c["chunk_id"]})

    batch_size = 50
    for i in range(0, len(ids), batch_size):
        end = min(i + batch_size, len(ids))
        collection.upsert(
            documents=docs[i:end],
            metadatas=metas[i:end],
            ids=ids[i:end],
        )

    # 4. 更新索引
    index.set(filename, ids, file_path)
    index.save()

    if verbose:
        print(f"  ✅ upsert完成: {len(chunks)} chunks")
    return True


def remove_note(filename, config, verbose=True):
    """从向量库删除单篇笔记"""
    vector_db_path = _resolve_vector_db(config)
    index = ChunkIndex(vector_db_path).load()

    entry = index.get(filename)
    if not entry or not entry.get("chunk_ids"):
        print(f"[REMOVE] {filename}: 未在索引中找到")
        return False

    collection = _get_or_create_collection(config, vector_db_path)
    old_ids = entry["chunk_ids"]

    try:
        collection.delete(ids=old_ids)
        if verbose:
            print(f"[REMOVE] {filename}: 已删除 {len(old_ids)} chunks")
    except Exception as e:
        print(f"[ERROR] 删除失败: {e}")
        return False

    index.remove(filename)
    index.save()
    return True


def rebuild_all(config, verbose=True):
    """全量重建向量库"""
    vector_db_path = _resolve_vector_db(config)
    _delete_collection(config, vector_db_path)

    # 删除旧索引
    index_path = vector_db_path / "index.json"
    if index_path.exists():
        index_path.unlink()

    notes = find_notes(config["obsidian_path"], config.get("notes_dir"))
    if not notes:
        print("[ERROR] 没有找到任何笔记")
        return False

    print(f"\n[REBUILD] 全量重建 — {len(notes)} 篇笔记\n")

    success = 0
    for note_path in notes:
        if upsert_note(note_path.name, config, verbose=False):
            success += 1
            print(f"  [{success}/{len(notes)}] {note_path.name}")

    # 保存快照
    idx = ChunkIndex(vector_db_path).load()
    total_chunks = sum(len(idx.data.get(n.name, {}).get("chunk_ids", [])) for n in notes)
    snapshot = {
        "built_at": str(datetime.datetime.now()),
        "notes_count": len(notes),
        "chunks_count": total_chunks,
    }
    (vector_db_path / "snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n✅ 全量重建完成: {success}/{len(notes)} 成功")
    return True


def scan_and_upsert(config, verbose=True):
    """检测新增/修改的文件，自动upsert"""
    notes = find_notes(config["obsidian_path"], config.get("notes_dir"))
    if not notes:
        print("[ERROR] 没有找到任何笔记")
        return

    vector_db_path = _resolve_vector_db(config)
    index = ChunkIndex(vector_db_path).load()
    indexed = set(index.filenames())

    new_files = []
    modified_files = []

    for note_path in notes:
        name = note_path.name
        if name not in indexed:
            new_files.append(note_path)
        else:
            entry = index.get(name)
            stored_mtime = entry.get("mtime", 0)
            current_mtime = note_path.stat().st_mtime
            if current_mtime > stored_mtime + 1:  # 1秒容差
                modified_files.append(note_path)

    print(f"\n[SCAN] 总计 {len(notes)} 篇笔记")
    print(f"  新增: {len(new_files)}")
    print(f"  修改: {len(modified_files)}")
    print(f"  未变: {len(notes) - len(new_files) - len(modified_files)}")

    if not new_files and not modified_files:
        print("  无需更新")
        return

    for f in new_files + modified_files:
        upsert_note(f.name, config, verbose=True)

    print(f"\n✅ 增量更新完成: +{len(new_files)}新 / ~{len(modified_files)}改")


# ─── 报告域（P2 刀4：报告 doc 进 chroma 带 status metadata） ─────────

REPORT_SOURCE_PREFIX = "report:"


def _report_docs_conn():
    """report_docs 权威表连接（view_lifecycle.db）。"""
    import sqlite3 as _sq
    db = Path(__file__).resolve().parent.parent / "data" / "views" / "view_lifecycle.db"
    con = _sq.connect(str(db))
    con.row_factory = _sq.Row
    return con


def _report_serialize(d: dict) -> str:
    """报告 JSON → 可检索文本（召回用；原文权威在 report_docs/report 文件）。"""
    parts = []
    for k in ("goal", "entity", "coreIssue", "summary"):
        v = d.get(k)
        if v:
            parts.append(f"{k}: {v}")
    for sec, key in (("facts", "text"), ("opinions", "text"), ("riskPoints", "risk"),
                     ("watchlist", "name"), ("scenarios", "name")):
        for it in d.get(sec) or []:
            if isinstance(it, dict):
                t = it.get(key)
                if t:
                    parts.append(f"{sec}: {t}")
    exp = d.get("holdingsExposure") or {}
    for e in exp.get("exposed") or []:
        if isinstance(e, dict) and e.get("name"):
            parts.append(f"持仓暴露: {e.get('name')} ({e.get('marketCode') or e.get('code') or ''}) "
                         f"仓位 {e.get('weightPct')}% 关系 {e.get('relation')}")
    # \n\n 段落分隔：chunk_markdown 按 \n\n 切段，单 \n 会整篇合成 1 大 chunk（embedding 截断）
    return "\n\n".join(parts)


def upsert_report(doc_id: str, config, verbose=True, force: bool = False) -> bool:
    """report_docs valid 报告 → chroma（metadata 带 status/doc_type/entity_key）。"""
    from pathlib import Path as _P
    root = _P(__file__).resolve().parent.parent
    con = _report_docs_conn()
    try:
        row = con.execute("SELECT * FROM report_docs WHERE doc_id=?", (doc_id,)).fetchone()
    finally:
        con.close()
    if not row:
        print(f"[ERROR] report_docs 无此登记: {doc_id}（先跑 report_docs.py scan）")
        return False
    if row["status"] != "valid":
        print(f"[SKIP] {doc_id} status={row['status']} 非 valid，不索引（用 --remove-report）")
        return False
    fpath = root / row["file_path"]
    if not fpath.exists():
        print(f"[ERROR] 报告文件不存在: {fpath}")
        return False
    try:
        import json as _json
        d = _json.loads(fpath.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] 报告解析失败 {doc_id}: {e}")
        return False

    vector_db_path = _resolve_vector_db(config)
    collection = _get_or_create_collection(config, vector_db_path)
    index = ChunkIndex(vector_db_path).load()
    key = REPORT_SOURCE_PREFIX + doc_id
    entry = index.get(key)

    # 内容未变跳过（sha256 比较；force=True 强制重索引，序列化逻辑升级后手动触发）
    if not force and entry and entry.get("sha256") and entry["sha256"] == row["file_sha256"][:16]:
        if verbose:
            print(f"[UNCHANGED] {key}（内容一致）")
        return True

    if entry and entry.get("chunk_ids"):
        try:
            collection.delete(ids=entry["chunk_ids"])
            if verbose:
                print(f"  删除旧chunks: {len(entry['chunk_ids'])} 条")
        except Exception as e:
            print(f"  [WARN] 删除旧chunks失败: {e}")

    text = _report_serialize(d)
    if not text.strip():
        print(f"  [WARN] {doc_id} 无可检索内容")
        return False
    source = key
    chunks = chunk_markdown(text, source, config["chunk_size"], config["chunk_overlap"])
    ids, docs, metas = [], [], []
    for c in chunks:
        ids.append(make_chunk_id(c["source"], c["chunk_id"]))
        docs.append(c["content"])
        metas.append({
            "source": c["source"], "section": c["section"], "chunk_id": c["chunk_id"],
            "doc_type": "report", "status": row["status"],
            "entity_key": row["entity_key"] or "",
            "linked_view_ids": row["linked_view_ids"] or "[]",
            "generated_at": row["generated_at"] or "",
        })
    batch_size = 50
    for i in range(0, len(ids), batch_size):
        collection.upsert(documents=docs[i:i + batch_size],
                          metadatas=metas[i:i + batch_size], ids=ids[i:i + batch_size])
    index.set(key, ids, file_path=fpath)
    index.save()
    if verbose:
        print(f"[UPSERT] {key}: {len(chunks)} chunks（status={row['status']}）")
    return True


def remove_report(doc_id: str, config, verbose=True) -> bool:
    """报告 chunks 移出 chroma（superseded/retracted 时调用）。"""
    vector_db_path = _resolve_vector_db(config)
    index = ChunkIndex(vector_db_path).load()
    key = REPORT_SOURCE_PREFIX + doc_id
    entry = index.get(key)
    if not entry or not entry.get("chunk_ids"):
        print(f"[REMOVE] {key}: 未在索引中")
        return False
    collection = _get_or_create_collection(config, vector_db_path)
    try:
        collection.delete(ids=entry["chunk_ids"])
        if verbose:
            print(f"[REMOVE] {key}: 已删除 {len(entry['chunk_ids'])} chunks")
    except Exception as e:
        print(f"[ERROR] 删除失败: {e}")
        return False
    index.remove(key)
    index.save()
    return True


def sync_reports(config, verbose=True, force: bool = True) -> None:
    """report_docs 全量同步：valid → upsert；superseded/retracted → remove。

    force 默认 True：报告量小（11 份级），全量重索引幂等安全——序列化/分块逻辑升级后
    无需手动逐份 force（notes 增量走 --scan 不受影响）。
    """
    con = _report_docs_conn()
    try:
        rows = con.execute("SELECT doc_id, status FROM report_docs ORDER BY doc_id").fetchall()
    finally:
        con.close()
    n_up = n_rm = n_skip = 0
    for r in rows:
        if r["status"] == "valid":
            if upsert_report(r["doc_id"], config, verbose=False, force=force):
                n_up += 1
            else:
                n_skip += 1
        else:
            if remove_report(r["doc_id"], config, verbose=False):
                n_rm += 1
    print(f"[SYNC-REPORTS] valid upsert {n_up}  非 valid remove {n_rm}  跳过 {n_skip}")


# ─── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="钱博士RAG向量库构建 — 支持增量")
    parser.add_argument("--rebuild", action="store_true", help="全量重建")
    parser.add_argument("--upsert", help="增量添加/更新单篇笔记（文件名）")
    parser.add_argument("--remove", help="删除单篇笔记（文件名）")
    parser.add_argument("--scan", action="store_true", help="自动检测并增量更新")
    parser.add_argument("--obsidian-path", help="覆盖Obsidian路径")
    parser.add_argument("--config", help="指定config.yaml路径")
    parser.add_argument("--sync-reports", action="store_true",
                        help="P2 刀4：报告同步（report_docs valid→upsert 带 status metadata；非 valid→remove）")
    parser.add_argument("--upsert-report", help="单份报告 upsert（doc_id）")
    parser.add_argument("--remove-report", help="单份报告 remove（doc_id）")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.obsidian_path:
        config["obsidian_path"] = args.obsidian_path

    if args.rebuild:
        rebuild_all(config)
    elif args.upsert:
        upsert_note(args.upsert, config)
    elif args.remove:
        remove_note(args.remove, config)
    elif args.scan:
        scan_and_upsert(config)
    elif args.sync_reports:
        sync_reports(config)
    elif args.upsert_report:
        upsert_report(args.upsert_report, config)
    elif args.remove_report:
        remove_report(args.remove_report, config)
    else:
        # 默认：如果向量库不存在则新建，否则提示
        vector_db_path = _resolve_vector_db(config)
        if not (vector_db_path / "chroma").exists():
            print("[INFO] 向量库不存在，执行全量构建...")
            rebuild_all(config)
        else:
            print("向量库已存在。可用操作：")
            print("  --rebuild       全量重建")
            print("  --upsert X      增量添加/更新单篇笔记")
            print("  --remove X      删除单篇笔记")
            print("  --scan          自动检测新增/修改")
            print("  --sync-reports  报告同步（valid→索引 / 非 valid→移除）")
