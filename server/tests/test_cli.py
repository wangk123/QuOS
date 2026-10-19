"""CLI 通道测试:输出约定(422 透传/连接失败/中文不转义)、文件传参、body 构造。"""
import json

import httpx

from app import cli


def _patch_client(monkeypatch, handler):
    monkeypatch.setattr("app.cli._make_client", lambda base: httpx.Client(
        base_url=base, transport=httpx.MockTransport(handler)))


def test_projects_happy_path(monkeypatch, capsys):
    _patch_client(monkeypatch, lambda req: httpx.Response(200, json={"ok": True}))
    assert cli.main(["projects"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {"ok": True}


def test_http_error_detail_to_stdout(monkeypatch, capsys):
    _patch_client(monkeypatch, lambda req: httpx.Response(
        422, json={"detail": {"hard_errors": [
            {"code": "QUOTE_NOT_FOUND", "rule_no": "FR-101", "detail": "x"}]}}))
    assert cli.main(["projects"]) == 1
    oe = capsys.readouterr()
    assert json.loads(oe.out)["detail"]["hard_errors"][0]["code"] == "QUOTE_NOT_FOUND"
    assert "HTTP 422" in oe.err


def test_connect_error_exit_2(monkeypatch, capsys):
    def boom(req):
        raise httpx.ConnectError("refused")

    _patch_client(monkeypatch, boom)
    assert cli.main(["projects"]) == 2
    assert "服务未启动" in capsys.readouterr().err


def test_chinese_not_escaped(monkeypatch, capsys):
    _patch_client(monkeypatch, lambda req: httpx.Response(200, json={"name": "云风控"}))
    cli.main(["projects"])
    assert "云风控" in capsys.readouterr().out


def test_import_draft_reads_md_file(monkeypatch, capsys, tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("# 测试文档\n\n- FR-101 必须支持批量导入。", encoding="utf-8")
    seen = {}

    def handler(req):
        seen["content"] = req.content.decode("utf-8", "replace")
        seen["path"] = str(req.url)
        seen["ctype"] = req.headers.get("content-type", "")
        return httpx.Response(200, json={"draft_id": 7})

    _patch_client(monkeypatch, handler)
    assert cli.main(["import-draft", "3", "--md", str(md)]) == 0
    assert seen["path"].endswith("/api/v1/projects/3/doc/draft/import")
    assert "multipart/form-data" in seen["ctype"]  # import 走 multipart(md 为文件 part)
    assert "# 测试文档" in seen["content"]
    assert json.loads(capsys.readouterr().out)["draft_id"] == 7


def test_import_draft_with_meta(monkeypatch, tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("正文", encoding="utf-8")
    meta = tmp_path / "meta.json"
    meta.write_text('{"FR-101": {"violation": "无法批量导入", "quote": "批量导入"}}',
                    encoding="utf-8")
    seen = {}

    def handler(req):
        seen["content"] = req.content.decode("utf-8", "replace")
        return httpx.Response(200, json={"draft_id": 7})

    _patch_client(monkeypatch, handler)
    assert cli.main(["import-draft", "3", "--md", str(md), "--meta", str(meta)]) == 0
    assert "无法批量导入" in seen["content"]  # rules_meta 以 form 字段(JSON 字符串)随 multipart 提交


def test_parser_questions_opts():
    ns = cli.build_parser().parse_args(["questions", "5", "--status", "answered"])
    assert ns.pid == 5 and ns.status == "answered"


def test_parser_changes_version():
    ns = cli.build_parser().parse_args(["changes", "5", "--version", "1.0.0"])
    assert ns.pid == 5 and ns.version == "1.0.0"


def test_missing_file_exit_2(monkeypatch, capsys):
    _patch_client(monkeypatch, lambda req: httpx.Response(200, json={}))
    assert cli.main(["import-draft", "3", "--md", "/no/such.md"]) == 2
    assert "不存在" in capsys.readouterr().err


def test_post_questions_body(monkeypatch, tmp_path):
    f = tmp_path / "q.json"
    f.write_text('[{"kind": "fill", "payload": {"q": "TBD-01 填空"}, "anchor": {}}]',
                 encoding="utf-8")
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["path"] = str(req.url)
        return httpx.Response(200, json=[])

    _patch_client(monkeypatch, handler)
    assert cli.main(["post-questions", "3", "--file", str(f)]) == 0
    assert seen["path"].endswith("/api/v1/projects/3/questions")
    assert seen["body"][0]["kind"] == "fill"


def test_bad_json_exit_2(monkeypatch, capsys, tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("正文", encoding="utf-8")
    meta = tmp_path / "meta.json"
    meta.write_text("{不是 json", encoding="utf-8")
    _patch_client(monkeypatch, lambda req: httpx.Response(200, json={}))
    assert cli.main(["import-draft", "3", "--md", str(md), "--meta", str(meta)]) == 2
    assert "JSON" in capsys.readouterr().err


def test_binary_file_exit_2(monkeypatch, capsys, tmp_path):
    md = tmp_path / "doc.md"
    md.write_bytes(b"\xff\xfe\x00binary")
    _patch_client(monkeypatch, lambda req: httpx.Response(200, json={}))
    assert cli.main(["import-draft", "3", "--md", str(md)]) == 2
    assert "UTF-8" in capsys.readouterr().err


def test_read_timeout_exit_2(monkeypatch, capsys):
    def slow(req):
        raise httpx.ReadTimeout("timed out")

    _patch_client(monkeypatch, slow)
    assert cli.main(["projects"]) == 2
    assert "请求失败" in capsys.readouterr().err


def test_import_draft_with_figures(monkeypatch, capsys, tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("## 1 章\n\n![主链路](figures/main-flow.html)\n", encoding="utf-8")
    figdir = tmp_path / "figures"
    figdir.mkdir()
    (figdir / "main-flow.html").write_text(
        "<!DOCTYPE html><html><body>x</body></html>", encoding="utf-8")
    seen = {}

    def handler(req):
        seen["content"] = req.content.decode("utf-8", "replace")
        seen["ctype"] = req.headers.get("content-type", "")
        return httpx.Response(200, json={"draft_id": 9})

    _patch_client(monkeypatch, handler)
    assert cli.main(["import-draft", "3", "--md", str(md), "--figures", str(figdir)]) == 0
    assert "multipart/form-data" in seen["ctype"]
    assert "main-flow.html" in seen["content"]
    assert "<!DOCTYPE html><html><body>x</body></html>" in seen["content"]
    assert json.loads(capsys.readouterr().out)["draft_id"] == 9
