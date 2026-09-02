#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钱博士 研究 Agent P1-a —— 研究目标 → 多源自主采集 → LLM 组装研究报告(协议 v2 JSON)

用法:
    python research_agent.py "复盘 8 月地产板块，推演 9 月政策情景" [--save]

研究流（Agent 自主补证据，观点库只是证据源之一）:
    1. LLM 提取研究实体与关键词
    2. 本地观点库检索 query_views_by_entity(entity)   ← 分析师观点（可能为空）
    3. 新闻采集: 东财快讯 + 新浪7x24, 关键词过滤去重   ← 客观事实源
    4. B站观点采集: yt-dlp bilisearch(带cookie)       ← 无分析师时补位（UP/播放/时长）
    5. LLM 组装: 素材 → 协议 v2 JSON（三桶+预期差+情景论证+观察清单+证据链）
    6. 输出 JSON 落盘 data/research/<ts>_<hash>.json 并打印

要点:
    - requests 一律 trust_env=False 直连（系统代理劫持坑）
    - 素材不足宁可少写/标注, 禁止编造; B站标题级线索标注"待核"
    - 输出仅研究分析, 合规约束在 prompt 层（不构成投资建议）
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# 直连（系统代理劫持坑: Clash 7897）
for _k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_k, None)

import requests
requests.packages.urllib3.disable_warnings()

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from view_store import query_views_by_entity  # noqa: E402
import jsonschema  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
COOKIES_FILE = PROJ / "data" / "bilibili_cookies.txt"
LLM_URL = "https://api.deepseek.com/chat/completions"
LLM_MODEL = "deepseek-v4-flash"  # 组织素材成报告，flash 够用且省
MAX_OUT_TOKENS = 4500

REPORT_SCHEMA_HINT = """{
  "coreIssue": "一句话核心矛盾（研究问题定义）",
  "summary": "结论摘要：复盘结论+推演判断+概率，300字内",
  "facts": [{"text": "客观事实", "source": "来源", "date": "YYYY-MM-DD"}],
  "opinions": [{"text": "观点内容", "analyst": "来源者", "date": "YYYY-MM-DD或近期", "side": "bull|bear|neutral"}],
  "crossCheck": {"consensus": ["观点共识1"], "disagreements": ["关键分歧1"]},
  "expectations": {"pricedIn": ["已定价共识1"], "upsideVars": ["超预期上行变量1"], "downsideVars": ["超预期下行变量1"]},
  "scenarios": [{"name": "情景A名", "condition": "触发条件", "outcome": "推演结果", "probability": 0.0-1.0, "rationale": "论证依据", "invalidation": "失效条件"}],
  "watchlist": [{"text": "跟踪项", "trigger": "触发含义"}],
  "evidence": [{"id": "证据id", "source": "来源", "date": "日期", "claim": "证据内容"}]
}"""


# ─── 1. LLM 调用 ─────────────────────────────────────────────

def call_llm(system: str, user: str, json_mode: bool = True, max_tokens: int = 2500) -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        # 回退: Hermes .env
        env_f = Path.home() / "AppData/Local/hermes/.env"
        if env_f.exists():
            m = re.search(r"DEEPSEEK_API_KEY=(\S+)", env_f.read_text(encoding="utf-8", errors="ignore"))
            key = m.group(1) if m else ""
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY 未设置")
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.4,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    s = requests.Session()
    s.trust_env = False
    s.proxies = {"http": None, "https": None}
    s.verify = False
    resp = s.post(LLM_URL, headers={**UA, "Authorization": f"Bearer {key}"}, json=payload, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    content = data["choices"][0]["message"].get("content") or ""
    if not content:
        raise RuntimeError(f"LLM 空返回: {json.dumps(data, ensure_ascii=False)[:300]}")
    return content


def llm_json(system: str, user: str, retries: int = 2, max_tokens: int = 4000) -> dict:
    last_err = ""
    for i in range(retries + 1):
        try:
            raw = call_llm(system, user, max_tokens=max_tokens)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                raise ValueError("not a dict")
            return obj
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(2)
    raise RuntimeError(f"LLM JSON 输出失败: {last_err}")


# ─── 2. 实体/关键词提取 ──────────────────────────────────────

def extract_keywords(goal: str) -> dict:
    sys_p = "你是财经检索词提取器。从研究目标提取检索要素，输出 JSON: {\"entity\":\"核心实体(1-2个中文词)\", \"keywords\":[\"检索词1\",\"检索词2\",\"检索词3\"], \"sector\":\"所属板块(如地产/黄金/半导体)或null\"}。关键词用于新闻与B站检索，每个 2-6 字。"
    try:
        return llm_json(sys_p, f"研究目标: {goal}", retries=1, max_tokens=1200)
    except Exception:
        # 规则兜底
        return {"entity": goal[:6], "keywords": [goal[:6]], "sector": None}


# ─── 3. 新闻采集（东财快讯 + 新浪7x24，直连） ────────────────

def _http_get(url: str, params: dict | None = None, timeout: int = 10):
    s = requests.Session()
    s.trust_env = False
    s.proxies = {"http": None, "https": None}
    s.verify = False
    return s.get(url, params=params, headers=UA, timeout=timeout)


def fetch_news_em(kw_list: list[str], page_size: int = 30) -> list[dict]:
    """东财快讯（国内快讯源）pageSize 超过 30 会返回 data=null（实测限流）"""
    out = []
    try:
        r = _http_get("https://np-listapi.eastmoney.com/comm/web/getFastNewsList", {
            "client": "web", "biz": "web_724", "fastColumn": "102", "sortEnd": "", "pageSize": str(page_size),
        })
        for n in (r.json().get("data") or {}).get("fastNewsList") or []:
            txt = (n.get("summary") or "").replace("\n", " ")
            if any(k and k in txt for k in kw_list):
                show = n.get("showTime") or ""
                out.append({"text": txt[:220], "date": show[:10], "source": "财联社/东财快讯"})
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 东财快讯失败: {e}", file=sys.stderr)
    return out


def fetch_news_sina(kw_list: list[str], pages: int = 2) -> list[dict]:
    """新浪 7x24 财经快讯（国际+国内）"""
    out = []
    try:
        for pg in range(1, pages + 1):
            r = _http_get("https://zhibo.sina.com.cn/api/zhibo/feed", {
                "page": str(pg), "page_size": "100", "zhibo_id": "152", "tag_id": "0",
            })
            feed = (((r.json().get("result") or {}).get("data") or {}).get("feed") or {}).get("list") or []
            if not feed:
                break
            for f in feed:
                txt = (f.get("rich_text") or "").replace("\n", " ")
                if any(k and k in txt for k in kw_list):
                    ts = f.get("create_time") or ""
                    out.append({"text": txt[:220], "date": ts[:10], "source": "新浪7x24"})
            time.sleep(0.4)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 新浪快讯失败: {e}", file=sys.stderr)
    return out


# ─── 4. B站观点采集（yt-dlp bilisearch，带 cookie） ──────────

def fetch_bilibili(keywords: list[str], limit: int = 8) -> list[dict]:
    # B站搜索对长组合词命中差：用最短的 2 个词（如 楼市/地产）
    words = sorted(keywords, key=len)[:2] if keywords else []
    query = " ".join(words) if words else ""
    print(f"      B站检索词: '{query}'", file=sys.stderr)
    try:
        cmd = [sys.executable, "-m", "yt_dlp", "--cookies", str(COOKIES_FILE),
               "--ignore-errors", "--skip-download", "--no-warnings",
               "--print", "%(title)s|||%(uploader)s|||%(duration)s|||%(view_count)s",
               f"bilisearch{limit}:{query}"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=150,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        items = []
        for line in (r.stdout or "").splitlines():
            parts = line.split("|||")
            if len(parts) >= 4 and parts[0] and parts[0] != "NA":
                items.append({
                    "title": parts[0][:80],
                    "uploader": parts[1][:30] if parts[1] != "NA" else "",
                    "duration": parts[2],
                    "views": parts[3],
                })
        return items[:limit]
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] B站检索失败: {e}", file=sys.stderr)
        return []


# ─── 5. 本地观点库检索 ───────────────────────────────────────

# 检索净化：去掉研究动作/宽泛词（会把海外宏观新闻滤进来），保留具体行业词
_NOISE_WORDS = {"复盘", "推演", "情景", "分析", "最近", "怎么", "如何", "政策面",
                "最新", "观点", "板块表现", "展望", "影响", "研究", "看法"}


def clean_keywords(kw_list: list[str], entity: str) -> list[str]:
    out = []
    for k in kw_list:
        k = (k or "").strip()
        if not k or k in _NOISE_WORDS:
            continue
        if k not in out:
            out.append(k)
    if entity and entity not in out:
        out.insert(0, entity)
    return out[:4] or [entity]

def fetch_local_views(entity: str, limit: int = 8) -> list[dict]:
    try:
        vs = query_views_by_entity(entity)
        # 兼容字段: date/analyst/stance/claim 或 view
        out = []
        for v in vs[:limit]:
            out.append({
                "text": str(v.get("claim") or v.get("view") or v.get("evidence") or "")[:200],
                "analyst": str(v.get("analyst") or "观点库")[:20],
                "date": str(v.get("date") or "")[:10],
                "side": str(v.get("stance") or "neutral").lower(),
            })
        return [o for o in out if o["text"]]
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 本地观点库查询失败: {e}", file=sys.stderr)
        return []


# ─── 6. 素材组装 → LLM 报告 ──────────────────────────────────

SCHEMA_PATH = PROJ / "docs" / "30_报告协议v2.schema.json"


def validate_report(report: dict) -> tuple[bool, list[str]]:
    """报告协议 v2 schema 校验：产出即校验，失败信息进 _meta 供审计与前端提示。"""
    if not SCHEMA_PATH.exists():
        return False, [f"schema 文件缺失: {SCHEMA_PATH}"]
    try:
        with SCHEMA_PATH.open(encoding="utf-8") as f:
            schema = json.load(f)
        validator = jsonschema.Draft202012Validator(schema)
        errors = [e.message for e in validator.iter_errors(report)]
        return (len(errors) == 0), errors[:8]
    except Exception as e:  # noqa: BLE001
        return False, [f"校验器异常: {e}"]




def build_report(goal: str, kw: dict, local_views: list, news: list, bili: list) -> dict:
    def fmt(items, keys=("text",)):
        if not items:
            return "（无）"
        lines = []
        for it in items[:12]:
            parts = []
            for k in keys:
                v = it.get(k)
                if v:
                    parts.append(str(v))
            lines.append("- " + " | ".join(parts))
        return "\n".join(lines)

    entity = kw.get("entity", goal[:8])
    material = f"""研究目标: {goal}
核心实体: {entity}

【A. 本地观点库（分析师结构化观点，可能为空=该实体无分析师覆盖）】
{fmt(local_views, ('analyst', 'date', 'side', 'text'))}

【B. 近期新闻（快讯源，注意日期，过时信息不得当现状）】
{fmt(news, ('date', 'source', 'text'))}

【C. B站财经视频（标题级线索，未看原片——只能作观点方向线索，标注"B站UP观点·待核"；不可当已证实事实）】
{fmt(bili, ('title', 'uploader', 'views'))}
"""
    sys_p = f"""你是资深财经研究分析师。基于给定素材，输出一份结构化研究报告 JSON（协议 v2）。

纪律（硬性）:
1. 事实(facts)只能来自素材 B 区（带来源和日期）；素材没有的客观数据不得编造。
2. 观点(opinions)来自 A 区(分析师, 标注原名+日期) 或 C 区(B站UP, analyst 写"B站·{'{uploader}'}"并注明观点为标题线索·待核)；A 区为空时明确不伪造分析师观点。
3. crossCheck/expectations 从素材观点差异与推理得出; 素材不足以支撑就写最保守的表述。
4. scenarios 概率必须给 rationale(论证依据, 写推理链), 总和不必=1 但要自洽; 所有推演是情景不是预测。
5. watchlist 每项带 trigger(什么信号出现→说明什么)。
6. evidence 列表对应报告引用的关键素材（id 用来源简称+日期）。
7. 若某类素材缺失, 在 summary 末尾用一句话说明"证据局限: X 源未覆盖"。
8. 全程不输出任何买卖/仓位/目标价建议。

JSON 输出结构（严格按此键名）:
{REPORT_SCHEMA_HINT}
"""
    obj = llm_json(sys_p, material, max_tokens=5000)
    # 落盘前补 meta
    obj["_meta"] = {
        "goal": goal,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "local_views": len(local_views),
            "news": len(news),
            "bilibili": len(bili),
        },
    }
    # 协议必填的确定性字段由代码补齐，不依赖 LLM 输出
    obj.setdefault("goal", goal)
    obj.setdefault("generatedAt", datetime.now().isoformat(timespec="seconds"))
    return obj


# ─── 主流程 ─────────────────────────────────────────────────

def run_research(goal: str, save: bool = True, job_id: str | None = None) -> dict:
    t0 = time.time()
    print(f"[1/6] 提取检索要素: {goal}")
    kw = extract_keywords(goal)
    entity = kw.get("entity") or goal[:8]
    kw_list = clean_keywords(kw.get("keywords") or [entity], entity)
    print(f"      实体={entity} 净化后关键词={kw_list}")

    print("[2/6] 本地观点库检索…")
    local_views = fetch_local_views(entity)
    print(f"      命中 {len(local_views)} 条")

    print("[3/6] 新闻采集（东财快讯+新浪7x24）…")
    news = fetch_news_em(kw_list)
    if len(news) < 5:
        news += fetch_news_sina(kw_list)
    # 去重（按前 60 字）
    seen, uniq = set(), []
    for n in news:
        key = n["text"][:60]
        if key not in seen:
            seen.add(key)
            uniq.append(n)
    news = uniq
    print(f"      命中 {len(news)} 条")

    print("[4/6] B站观点检索（yt-dlp bilisearch）…")
    bili = fetch_bilibili(kw_list)
    print(f"      命中 {len(bili)} 条")

    print("[5/6] LLM 组装研究报告…")
    report = build_report(goal, kw, local_views, news, bili)

    ok, errs = validate_report(report)
    report.setdefault("_meta", {})["schema_valid"] = ok
    if errs:
        report["_meta"]["schema_errors"] = errs
    if job_id:
        report["_meta"]["job_id"] = job_id
    print(f"[5b/6] 协议 v2 schema 校验: {'通过' if ok else '失败: ' + '; '.join(errs)}")

    print(f"[6/6] 完成，耗时 {time.time() - t0:.0f}s")
    if save:
        out_dir = PROJ / "data" / "research"
        out_dir.mkdir(exist_ok=True)
        h = hashlib.md5(goal.encode()).hexdigest()[:8]
        fname = out_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{h}.json"
        fname.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已保存: {fname}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("goal", help="研究目标，如: 复盘 8 月地产板块，推演 9 月政策情景")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--job-id", default=None, help="任务ID(由调用方分配,写入报告 _meta.job_id)")
    args = ap.parse_args()
    rep = run_research(args.goal, save=not args.no_save, job_id=args.job_id)
    print(json.dumps(rep, ensure_ascii=False, indent=1)[:3000])
