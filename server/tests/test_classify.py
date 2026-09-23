# server/tests/test_classify.py
from app.core.classify import classify_text, classify_file

def test_git_ssh_recognized_as_repo():
    r = classify_text("git@git.internal:riskcloud/core.git feature/retry")
    assert r["type"] == "仓库" and r["name"] == "git@git.internal:riskcloud/core.git"
    assert r["ext"] == "@feature/retry" and r["stars"] == 3

def test_git_https_recognized():
    r = classify_text("https://github.com/foo/bar.git")
    assert r["type"] == "仓库"

def test_branch_with_at():
    r = classify_text("git@x.com:a/b.git@release/1.0")
    assert r["ext"] == "@release/1.0"

def test_plain_text():
    r = classify_text("张开发：重试的时候不用查余额")
    assert r["type"] == "文本" and r["stars"] == 2 and "文本·粘贴" in r["ext"]

def test_url_text():
    r = classify_text("https://confluence.example.com/page/123")
    assert r["type"] == "文本" and "链接" in r["ext"]

def test_file_types():
    assert classify_file("a.zip") == "压缩包"
    assert classify_file("b.DOCX") == "文档"
    assert classify_file("c.png") == "截图"
    assert classify_file("d.unknown") == "文档"
