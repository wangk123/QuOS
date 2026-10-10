# server/app/storage/profiles.py
import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.storage import tree
from app.storage.project import slugify

PROFILE_DIR = "profiles"
OLD_DIR = "cards"  # 术语迁移前（卡片→用户画像）的目录名，读到即整目录改名
ROOT_NODE = "__root__"  # 根画像的寻址键：不在功能树上，直接以该常量存取

_SECTIONS = [("flow", "主流程"), ("states", "状态机"), ("boundaries", "异常边界"),
             ("note", "补充说明"), ("deps", "依赖")]
_SECTION_KEY = {"规则": "rules", **{t: k for k, t in _SECTIONS}}


class ProfileRule(BaseModel):
    id: str
    text: str
    src: str
    conf: str


class Profile(BaseModel):
    node: str
    kind: str = "leaf"  # root | module | leaf（画像从仅叶节点扩展到全树三层）
    goal: str = ""
    entry: str = ""
    flow: str = ""
    rules: list[ProfileRule] = Field(default_factory=list)
    states: str = ""
    boundaries: str = ""
    note: str = ""
    deps: str = ""


def _dump(profile: Profile) -> str:
    lines = ["---", f"node: {profile.node}", f"kind: {profile.kind}",
             f"goal: {profile.goal}", f"entry: {profile.entry}",
             "---", "", f"# {profile.node}", ""]
    for key, title in _SECTIONS:
        lines.append(f"## {title}")
        lines.append(getattr(profile, key))
        lines.append("")
    lines += ["## 规则", ""]
    if profile.rules:
        lines += ["| ID | 规则 | 来源 | 置信度 |", "|---|---|---|---|"]
        for r in profile.rules:
            text = r.text.replace("|", "\\|")
            lines.append(f"| {r.id} | {text} | {r.src} | {r.conf} |")
    lines.append("")
    return "\n".join(lines)


def _parse_rules(body: list[str]) -> list[ProfileRule]:
    rows = [ln for ln in body if ln.strip().startswith("|")]
    data = [r for r in rows if set(r.replace("|", "").replace(" ", "")) != {"-"}]
    rules = []
    for row in data[1:]:  # 首行为表头
        cells = [c.strip().replace("\\|", "|")
                 for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]
        if len(cells) >= 4:
            rules.append(ProfileRule(id=cells[0], text=cells[1], src=cells[2], conf=cells[3]))
    return rules


def _parse(text: str) -> Profile:
    lines = text.splitlines()
    meta, i = {}, 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            k, _, v = lines[i].partition(":")
            meta[k.strip()] = v.strip()
            i += 1
        i += 1
    bodies: dict[str, list[str]] = {k: [] for k in _SECTION_KEY.values()}
    cur = None
    for ln in lines[i:]:
        if ln.startswith("## "):
            cur = _SECTION_KEY.get(ln[3:].strip())
        elif cur:
            bodies[cur].append(ln)
    kwargs: dict = {"node": meta.get("node", ""), "kind": meta.get("kind", "leaf"),
                    "goal": meta.get("goal", ""), "entry": meta.get("entry", ""),
                    "rules": _parse_rules(bodies["rules"])}
    for key, _ in _SECTIONS:
        kwargs[key] = "\n".join(bodies[key]).strip()
    return Profile(**kwargs)


def _dir(root) -> Path:
    d = Path(root) / PROFILE_DIR
    if not d.exists():
        old = Path(root) / OLD_DIR
        if old.is_dir():
            old.rename(d)  # 旧数据目录整体迁移（含历史版本文件）
    return d


def save_profile(root, node_path: str, profile: Profile) -> Path:
    d = _dir(root)
    d.mkdir(parents=True, exist_ok=True)
    name = slugify(node_path.rsplit("/", 1)[-1])
    f, n = d / f"{name}.md", 2
    while f.exists():
        f = d / f"{name}-{n}.md"
        n += 1
    f.write_text(_dump(profile), "utf-8")
    return f


def _file_no(f: Path) -> int:
    m = re.match(r"^(.*)-(\d+)$", f.stem)
    return int(m.group(2)) if m else 1


def _latest_profiles(root) -> dict[str, Profile]:
    """node -> 最新用户画像（同节点取后缀数字最大的文件；重复 save 视为迭代，最新生效）"""
    d = _dir(root)
    if not d.exists():
        return {}
    best: dict[str, tuple[int, Profile]] = {}
    for f in sorted(d.glob("*.md")):
        profile = _parse(f.read_text("utf-8"))
        no = _file_no(f)
        if profile.node not in best or no > best[profile.node][0]:
            best[profile.node] = (no, profile)
    return {node: p for node, (_, p) in best.items()}


def load_profile(root, node_path: str) -> Profile | None:
    return _latest_profiles(root).get(node_path)


def load_latest(root) -> list[Profile]:
    """各节点最新用户画像列表（同节点多版本取最新；子树聚合等按节点视图用）"""
    return list(_latest_profiles(root).values())


def load_all(root) -> list[Profile]:
    d = _dir(root)
    if not d.exists():
        return []
    return [_parse(f.read_text("utf-8")) for f in sorted(d.glob("*.md"))]


def _humanize(s: str) -> str:
    """验证口径 → 需求陈述（AI 核验的 test intent 不进交付文档）：
    「验证X的行为/功能/逻辑。」与「验证X。」两种形态去壳；「验证码」等名词不误伤"""
    s = s.strip()
    m = re.fullmatch(r"验证(.{1,120}?)的(行为|功能|逻辑)。?", s)
    if m:
        return m.group(1) + "。"
    m = re.fullmatch(r"验证(?!码)(.{8,})。?", s)
    return m.group(1) + "。" if m else s


def _is_count_noise(s: str) -> bool:
    """计数型边界（如「0 实证」「1 实证、2 文档」）是质检口径，不是需求内容"""
    return bool(re.fullmatch(r"\d+\s*[实证文档推测待旧]{2,4}(、\d+\s*[实证文档推测待旧]{2,4})*。?", s.strip()))


def _render_profile(profile: Profile, with_title: bool = True) -> list[str]:
    """叶子画像：粗体小节标签 + 规则列表化（无 ID/来源/置信度）+ 状态机按组拆行"""
    out = [f"### {profile.node}", ""] if with_title else []
    if profile.goal:
        out += [f"**目标**：{_humanize(profile.goal)}", ""]
    if profile.entry:
        out += [f"**入口**：{_humanize(profile.entry)}", ""]
    if profile.flow:
        out += ["**主流程**", profile.flow, ""]
    if profile.rules:
        out += ["**规则**"] + [f"- {r.text}" for r in profile.rules] + [""]
    for key, title in _SECTIONS[1:-1]:
        v = getattr(profile, key)
        if not v or (key == "boundaries" and _is_count_noise(v)):
            continue
        if key == "states":
            out += [f"**{title}**", v.replace("；", "\n"), ""]  # 每组状态一行
        else:
            out += [f"**{title}**", _humanize(v), ""]
    return out


def _render_overview(profile: Profile) -> list[str]:
    """根画像总览章：goal/entry/flow/boundaries/note 按 h3 小节渲染，空字段跳过；全空时整章跳过"""
    sections = [(key, title) for key, title in [("goal", "目标"), ("entry", "入口"), ("flow", "主流程"),
                                                ("boundaries", "异常边界"), ("note", "补充说明")]
                if getattr(profile, key) and not (key == "boundaries" and _is_count_noise(getattr(profile, key)))]
    if not sections:
        return []
    out = ["## 需求总览", ""]
    for key, title in sections:
        v = getattr(profile, key)
        out += [f"### {title}", _humanize(v), ""]
    return out


def _render_module(profile: Profile) -> list[str]:
    """模块画像直接挂模块章 h2 下（不再出同名 h3，双标题冗余）；全空整段跳过"""
    if not profile.goal and not profile.boundaries:
        return []
    out = []
    if profile.goal:
        out.append(f"**职责**：{_humanize(profile.goal)}")
    if profile.boundaries and not _is_count_noise(profile.boundaries):
        out.append(f"**边界**：{_humanize(profile.boundaries)}")
    return out + [""] if out else []


def _doc_version(root: Path) -> str | None:
    """文档头版本行：当前基线（HEAD 所指 tag）；无 git / 无版本返回 None"""
    try:
        from app.storage import gitops
        for item in gitops.list_baselines(root):
            if item.get("cur"):
                return item["tag"]
    except Exception:
        pass
    return None


def export_doc(root) -> str:
    root = Path(root)
    profiles = _latest_profiles(root)
    nodes = tree.load(root)

    # 文档头：项目名 / 版本（当前基线）/ 生成时间 / 范围统计
    n_rules = sum(len(p.rules) for p in profiles.values() if p.node != ROOT_NODE)
    out = [f"# {root.name} · 需求文档", ""]
    ver = _doc_version(root)
    if ver:
        out += [f"- 版本：{ver}（当前基线）", ""]
    from datetime import datetime
    out += [f"- 生成：{datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
            f"- 范围：{len(nodes)} 个模块 · {n_rules} 条规则", ""]

    if ROOT_NODE in profiles:
        out += _render_overview(profiles[ROOT_NODE])
    used: set[str] = {ROOT_NODE}  # 根画像已入开篇总览，不进孤儿段

    def walk(items: list[tree.Node], prefix: str, depth: int):
        for n in items:
            full = f"{prefix}/{n.name}" if prefix else n.name
            out.append("#" * (depth + 2) + " " + n.name)  # 章节标题用节点名，层级由标题层级表达
            out.append("")
            profile = profiles.get(full)
            if profile is not None:
                used.add(full)
                if profile.kind == "module":
                    out.extend(_render_module(profile))
                else:
                    out.extend(_render_profile(profile, with_title=False))
            walk(n.children, full, depth + 1)

    walk(nodes, "", 0)
    orphans = [(node, p) for node, p in profiles.items() if node not in used]
    if orphans:
        out += ["## 附录：未挂树的画像", "", "> 以下画像的节点不在当前大纲树中，保留全路径供追溯", ""]
        for node, profile in orphans:
            out.extend(_render_profile(profile))
    return "\n".join(out).rstrip() + "\n"
