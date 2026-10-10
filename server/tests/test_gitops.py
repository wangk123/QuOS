# gitops 直测：tmp 真仓库覆盖版本号三规则（API 视角在 test_api.py）
import pytest
from app.storage import gitops


@pytest.fixture
def root(tmp_path):
    (tmp_path / "evidence.json").write_text("{}", "utf-8")
    return tmp_path


def test_save_version_tag_and_return(root):
    r = gitops.save_baseline(root, "1.2.3", "首个语义化版本")
    assert r["tag"] == "v1.2.3" and r["version"] == "1.2.3" and len(r["commit"]) >= 7


def test_save_rejects_bad_format(root):
    for bad in ["v1.2.3", "1.2", "1.2.3.4", "a.b.c", ""]:
        with pytest.raises(ValueError, match="格式"):
            gitops.save_baseline(root, bad, "x")


def test_save_rejects_duplicate(root):
    gitops.save_baseline(root, "1.0.0", "一")
    with pytest.raises(ValueError, match="已存在"):
        gitops.save_baseline(root, "1.0.0", "二")


def test_save_rejects_lower_than_max(root):
    gitops.save_baseline(root, "1.2.1", "一")
    for low in ["1.2.0", "1.1.9", "0.9.9"]:
        with pytest.raises(ValueError, match="不得低于"):
            gitops.save_baseline(root, low, "二")


def test_save_allows_high_version_with_legacy_tags(root):
    """旧 vN 不参与倒挂下限：存量 v5 仍可存 1.0.0"""
    gitops._git(root, "init")
    gitops._git(root, "add", "-A")
    gitops._git(root, "commit", *gitops._commit_args(root), "-m", "旧存档")
    gitops._git(root, "tag", "v5")
    r = gitops.save_baseline(root, "1.0.0", "新起点")
    assert r["tag"] == "v1.0.0"


def test_save_without_changes_still_tags(root):
    gitops.save_baseline(root, "1.0.0", "一")
    r = gitops.save_baseline(root, "1.0.1", "无变更")
    assert r["tag"] == "v1.0.1" and r["commit"]  # 无变更 tag 指向当前 commit


def test_save_without_changes_keeps_note(root):
    """无变更存版说明不丢：恒建空 commit，note 进 message——
    若跳过 commit，tag 挂旧 commit、时间线显示旧 message（线上 1.0.0 显示"V0.0.2"根因）"""
    gitops.save_baseline(root, "1.0.0", "第一版说明")
    gitops.save_baseline(root, "1.0.1", "本次输入的说明")
    items = {i["tag"]: i for i in gitops.list_baselines(root)}
    assert items["v1.0.0"]["note"] == "第一版说明"
    assert items["v1.0.1"]["note"] == "本次输入的说明"


def test_list_fields_and_semver_order(root):
    gitops.save_baseline(root, "1.0.0", "第一版说明")
    c1 = gitops._git(root, "rev-list", "-n1", "HEAD")
    (root / "rules.json").write_text("[]", "utf-8")
    gitops.save_baseline(root, "1.2.0", "第二版")
    gitops._git(root, "tag", "v0", c1)  # 旧格式混排：v0 指向 1.0.0 的 commit → (0,0,0) 排最前且非当前
    items = gitops.list_baselines(root)
    assert [i["tag"] for i in items] == ["v0", "v1.0.0", "v1.2.0"]
    assert items[2]["note"] == "第二版" and items[2]["time"] > 0
    assert items[2]["cur"] is True and items[0]["cur"] is False  # HEAD 所指=当前


def test_list_empty_without_git(root):
    assert gitops.list_baselines(root) == []


def test_restore_resets_content_and_cleans(root):
    gitops.save_baseline(root, "1.0.0", "一")
    (root / "rules.json").write_text('["新版内容"]', "utf-8")
    (root / "untracked.txt").write_text("未存版文件", "utf-8")
    gitops.restore_baseline(root, "v1.0.0")
    assert not (root / "rules.json").exists()      # 回到该版没有此文件
    assert not (root / "untracked.txt").exists()   # 未跟踪文件被清理
    assert gitops.list_baselines(root)[0]["cur"] is True  # HEAD 回到该版


def test_restore_unknown_tag_raises(root):
    gitops.save_baseline(root, "1.0.0", "一")
    with pytest.raises(KeyError):
        gitops.restore_baseline(root, "v9.9.9")


def test_delete_removes_tag_keeps_commit(root):
    gitops.save_baseline(root, "1.0.0", "一")
    commit = gitops.list_baselines(root)[0]["commit"]
    gitops.delete_baseline(root, "v1.0.0")
    assert gitops.list_baselines(root) == []
    assert gitops._git(root, "cat-file", "-t", commit) == "commit"  # 数据仍在 git 历史
    gitops.delete_baseline(root, "v1.0.0")  # 幂等


def test_save_on_bare_empty_project(tmp_path):
    """空项目（无文件无 commit）直接存首版：建空 commit 挂 tag，不 500"""
    r = gitops.save_baseline(tmp_path, "1.0.0", "空项目首版")
    assert r["tag"] == "v1.0.0" and len(r["commit"]) >= 7
    assert gitops.list_baselines(tmp_path)[0]["note"] == "空项目首版"


def test_list_with_annotated_tag(root):
    """废弃文案引导用户 git 手动找回——重新打的 annotated tag 不能让列表 500；
    cur 判定/commit 显示须穿透 tag object 取真实 commit"""
    gitops.save_baseline(root, "1.0.0", "一")
    gitops._git(root, "tag", "-a", "v1.5.0", "-m", "手动找回的注解版")
    items = gitops.list_baselines(root)
    assert [i["tag"] for i in items] == ["v1.0.0", "v1.5.0"]
    a = items[1]
    assert a["commit"] == items[0]["commit"]  # *objectname 穿透到 commit
    assert a["cur"] is True and a["time"] > 0
    assert a["note"]  # annotated message 或指向 commit 的 subject，非空即可
