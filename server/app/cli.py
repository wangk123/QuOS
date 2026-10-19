"""CLI 通道:agent 对接端点的命令行包装,用法见 docs/quos-agent-api.md「CLI 调用」。"""
import argparse
import json
import os
import sys

import httpx


def _make_client(base: str) -> httpx.Client:
    # trust_env=False:本机系统代理会劫持对 127.0.0.1 的请求,造成「服务未启动」误报
    return httpx.Client(base_url=base, trust_env=False, timeout=30)


def _print_json(resp: httpx.Response) -> None:
    try:
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(resp.text)


def _request(client: httpx.Client, method: str, path: str, *,
             json_body=None, params=None, files=None, data=None) -> int:
    try:
        resp = client.request(method, path, json=json_body, params=params,
                              files=files, data=data)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        print(f"连接失败({client.base_url})：服务未启动？./start.sh", file=sys.stderr)
        return 2
    except httpx.HTTPError as exc:  # ReadTimeout/RemoteProtocolError 等:非服务端语义错误
        print(f"请求失败：{exc!r}", file=sys.stderr)
        return 2
    _print_json(resp)
    if resp.status_code >= 400:
        print(f"HTTP {resp.status_code}: {method} {path}", file=sys.stderr)
        return 1
    return 0


class _CliError(Exception):
    """输入文件不可用(不存在/读失败/非法 JSON),main 统一转退出码 2。"""


def _read_file(path: str, what: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"{what}不存在：{path}", file=sys.stderr)
        raise _CliError from None
    except OSError as exc:
        print(f"读取{what}失败：{exc.strerror} ({path})", file=sys.stderr)
        raise _CliError from None
    except UnicodeDecodeError:
        print(f"{what}不是 UTF-8 文本：{path}", file=sys.stderr)
        raise _CliError from None


def _read_json(path: str, what: str):
    text = _read_file(path, what)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"{what}不是合法 JSON：{exc.msg} (line {exc.lineno}, {path})", file=sys.stderr)
        raise _CliError from None


def _pid_path(pid: int, suffix: str) -> str:
    return f"/api/v1/projects/{pid}/{suffix}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="QuOS agent 对接 CLI(基址默认 http://127.0.0.1:8000)")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="平台基址")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("projects", help="项目列表(找 pid)")
    sub.add_parser("materials", help="材料清单(parsed_text 出处源)").add_argument("pid", type=int)
    sub.add_parser("baseline", help="当前基线(无定稿返回 empty:true)").add_argument("pid", type=int)
    sub.add_parser("draft", help="当前 reviewing 草案").add_argument("pid", type=int)

    p = sub.add_parser("import-draft", help="markdown 草案导入(推荐提交路径)")
    p.add_argument("pid", type=int)
    p.add_argument("--md", required=True, help="markdown 文件路径")
    p.add_argument("--figures", help="图文件目录(diagram-design HTML 图集,md 整行引用)")
    p.add_argument("--meta", help="rules_meta JSON 文件({规则号: {violation, quote}})")
    p.add_argument("--one-pager", help="需求一页纸 markdown 文件(伴生随草案入库)")

    p = sub.add_parser("submit-draft", help="手工 DocPayload 提交")
    p.add_argument("pid", type=int)
    p.add_argument("--file", required=True, help="payload JSON 文件路径")

    p = sub.add_parser("questions", help="批注列表")
    p.add_argument("pid", type=int)
    p.add_argument("--status", help="过滤状态(pending/answered/withdrawn)")

    p = sub.add_parser("post-questions", help="批量提交消歧批注")
    p.add_argument("pid", type=int)
    p.add_argument("--file", required=True, help="批注 JSON 数组文件路径")

    sub.add_parser("versions", help="版本列表").add_argument("pid", type=int)
    p = sub.add_parser("changes", help="变更记录")
    p.add_argument("pid", type=int)
    p.add_argument("--version", help="过滤版本号")
    return parser


def _dispatch(args, client: httpx.Client) -> int:
    if args.cmd == "projects":
        return _request(client, "GET", "/api/v1/projects")
    if args.cmd == "materials":
        return _request(client, "GET", _pid_path(args.pid, "materials"))
    if args.cmd == "baseline":
        return _request(client, "GET", _pid_path(args.pid, "doc/baseline"))
    if args.cmd == "draft":
        return _request(client, "GET", _pid_path(args.pid, "doc/draft"))
    if args.cmd == "import-draft":
        data: dict = {}
        files = [("md", ("doc.md", _read_file(args.md, "markdown 文件").encode(), "text/markdown"))]
        if args.meta:
            data["rules_meta"] = json.dumps(          # multipart 下 rules_meta 为 form 字段(JSON 字符串)
                _read_json(args.meta, "rules_meta 文件"), ensure_ascii=False)
        if args.one_pager:
            data["one_pager_md"] = _read_file(args.one_pager, "一页纸文件")
        if args.figures:
            fdir = args.figures
            if not os.path.isdir(fdir):
                print(f"图目录不存在：{fdir}", file=sys.stderr)
                raise _CliError from None
            for name in sorted(os.listdir(fdir)):
                if not name.endswith(".html"):
                    continue
                files.append(("figures", (name,
                            _read_file(os.path.join(fdir, name), "图文件").encode(), "text/html")))
        return _request(client, "POST", _pid_path(args.pid, "doc/draft/import"),
                        files=files, data=data or None)
    if args.cmd == "submit-draft":
        return _request(client, "POST", _pid_path(args.pid, "doc/draft"),
                        json_body=_read_json(args.file, "payload 文件"))
    if args.cmd == "questions":
        return _request(client, "GET", _pid_path(args.pid, "questions"),
                        params={"status": args.status} if args.status else None)
    if args.cmd == "post-questions":
        return _request(client, "POST", _pid_path(args.pid, "questions"),
                        json_body=_read_json(args.file, "批注文件"))
    if args.cmd == "versions":
        return _request(client, "GET", _pid_path(args.pid, "doc/versions"))
    if args.cmd == "changes":
        return _request(client, "GET", _pid_path(args.pid, "doc/changes"),
                        params={"version": args.version} if args.version else None)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = _make_client(args.base)
    try:
        return _dispatch(args, client)
    except _CliError:
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
