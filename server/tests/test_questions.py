"""批注批量提交 / 作答 API 测试。"""


def _proj(client) -> int:
    return client.post("/api/v1/projects", json={"name": "P"}).json()["id"]


def test_batch_submit_returns_same_batch_id(client):
    pid = _proj(client)
    r = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "choice", "payload": {"q": "边界?", "options": [
            {"k": "A", "t": "成功"}, {"k": "B", "t": "取消"}]},
         "anchor": {"chapter_id": "c3", "rule_no": "R12", "seg": "30 分钟未支付"}},
        {"kind": "fill", "payload": {"q": "作用域?"},
         "anchor": {"chapter_id": "c4"}},
        {"kind": "confirm", "payload": {"q": "确认 30 天?"},
         "anchor": {"chapter_id": "c4", "rule_no": "R16", "seg": "30 天"}},
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 3
    assert len({q["batch_id"] for q in body}) == 1 and body[0]["batch_id"]
    assert all(q["source"] == "agent" and q["status"] == "pending" for q in body)


def test_choice_requires_two_options(client):
    pid = _proj(client)
    r = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "choice", "payload": {"q": "x?", "options": [{"k": "A", "t": "a"}]},
         "anchor": {}}])
    assert r.status_code == 422


def test_choice_rejects_malformed_options(client):
    """options 元素须为 {k, t} 对象:字符串数组/缺键 422 打回(前端按 o.k/o.t 渲染)。"""
    pid = _proj(client)
    r = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "choice", "payload": {"q": "口径?", "options": ["A：维持", "B：只留已实现"]},
         "anchor": {"chapter_id": "c1"}}])
    assert r.status_code == 422 and "k, t" in r.json()["detail"]
    r = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "choice", "payload": {"q": "口径?", "options": [{"k": "A"}, {"k": "B", "t": "b"}]},
         "anchor": {}}])
    assert r.status_code == 422 and "k, t" in r.json()["detail"]


def test_fill_requires_question_text(client):
    pid = _proj(client)
    r = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "fill", "payload": {"q": ""}, "anchor": {}}])
    assert r.status_code == 422


def test_q_required_for_all_kinds(client):
    """q 为所有题型必填:choice/confirm 缺 q(或误用 question 字段名)一律 422,不得入库成空白卡。"""
    pid = _proj(client)
    r = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "choice", "payload": {"question": "口径?", "options": [{"k": "A", "t": "a"}, {"k": "B", "t": "b"}]},
         "anchor": {}}])
    assert r.status_code == 422 and "q" in r.json()["detail"] and "question" in r.json()["detail"]
    r = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "confirm", "payload": {"klabel": "确认"}, "anchor": {}}])
    assert r.status_code == 422 and "payload.q" in r.json()["detail"]


def test_kind_restricted_to_four(client):
    pid = _proj(client)
    r = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "essay", "payload": {"q": "x"}, "anchor": {}}])
    assert r.status_code == 422


def test_answer_by_kind_and_fetch_answered(client):
    pid = _proj(client)
    qs = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "choice", "payload": {"q": "边界?", "options": [
            {"k": "A", "t": "成功"}, {"k": "B", "t": "取消"}]},
         "anchor": {"chapter_id": "c3"}},
        {"kind": "fill", "payload": {"q": "作用域?"}, "anchor": {"chapter_id": "c4"}},
    ]).json()
    c1, f1 = qs

    r = client.post(f"/api/v1/questions/{c1['id']}/answer", json={"answer": {"key": "A"}})
    assert r.status_code == 200 and r.json()["status"] == "answered"
    r = client.post(f"/api/v1/questions/{f1['id']}/answer", json={"answer": {"text": "租户内唯一"}})
    assert r.status_code == 200

    answered = client.get(f"/api/v1/projects/{pid}/questions?status=answered").json()
    by_id = {q["id"]: q for q in answered}
    assert by_id[c1["id"]]["answer"]["key"] == "A"
    assert by_id[f1["id"]]["answer"]["text"] == "租户内唯一"
    assert by_id[f1["id"]]["answered_at"]

    pending = client.get(f"/api/v1/projects/{pid}/questions?status=pending").json()
    assert [q["id"] for q in pending] == []


def test_answer_missing_question_404(client):
    assert client.post("/api/v1/questions/999/answer",
                       json={"answer": {"text": "x"}}).status_code == 404


def test_reanswer_overwrites_previous(client):
    """重新作答 = 覆盖(终审 I3/I2:scan 逐项提交与 undo 重答依赖覆盖语义)。"""
    pid = _proj(client)
    q = client.post(f"/api/v1/projects/{pid}/questions", json=[
        {"kind": "fill", "payload": {"q": "x"}, "anchor": {}}]).json()[0]
    assert client.post(f"/api/v1/questions/{q['id']}/answer",
                       json={"answer": {"text": "a"}}).status_code == 200
    r = client.post(f"/api/v1/questions/{q['id']}/answer", json={"answer": {"text": "b"}})
    assert r.status_code == 200 and r.json()["answer"]["text"] == "b"
