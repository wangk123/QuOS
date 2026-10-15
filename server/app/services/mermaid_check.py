"""mermaid 语法真实校验:node 端跑 mermaid.parse(复用前端已装依赖,不新增包)。

node 无 DOM,合法图会在 sanitize 阶段抛环境错误(DOMPurify)——但语法解析先于它执行,
故以「Parse error/Lexical error」前缀判定真语法错误,其余视为通过(不误杀)。
"""
import json
import os
import subprocess
from pathlib import Path

_WEB = Path(__file__).resolve().parents[3] / "web"
_MERMAID_URL = (_WEB / "node_modules" / "mermaid" / "dist" / "mermaid.esm.min.mjs").as_uri()

_NODE_SCRIPT = """
const mermaid = (await import(process.env.MERMAID_URL)).default;
const srcs = JSON.parse(await new Promise(r => { let d=''; process.stdin.on('data',c=>d+=c).on('end',()=>r(d)); }));
const out = [];
for (const s of srcs) {
  try { await mermaid.parse(s); out.push(null); }
  catch (e) { const m = String(e.message || e); out.push(/^(Parse|Lexical) error/.test(m) ? m.split('\\n').slice(0,2).join(' | ') : null); }
}
process.stdout.write(JSON.stringify(out));
"""


def check_mermaid(sources: list[str]) -> list[str]:
    """返回语法错误清单(与 sources 等长,null=通过/无法判定)。node 不可用时返回全 None(不阻塞导入)。"""
    if not sources:
        return []
    try:
        r = subprocess.run(
            ["node", "--input-type=module", "-e", _NODE_SCRIPT],
            input=json.dumps(sources).encode(), capture_output=True, timeout=30,
            env={**os.environ, "MERMAID_URL": _MERMAID_URL},
        )
        return json.loads(r.stdout) if r.returncode == 0 else [None] * len(sources)
    except Exception:
        return [None] * len(sources)
