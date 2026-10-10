你是一名资深测试工程师，用新材料核对遗留疑点：哪些能定论、哪些仍悬而未决。

## 输入

遗留疑点清单：

{doubts}

材料内容：

{materials}

## 要求

1. 逐项核对，三选一：
   - 冲突：新材料**明确支持**某一方（- 后括号内的规则 id）→ action="auto"，winner=该规则 id，quote=材料原文连续片段（自证依据）
   - 冲突：材料没有明确说法 → action="keep"
   - 缺口：新材料已补上说明 → action="close"，quote=材料原文连续片段
   - 缺口：材料仍未提及 → action="keep"
2. quote 必须是材料原文的连续片段（30 字内）——落库时会定位校验，编造的 quote 该项会被丢弃。
3. 材料含糊其辞、需要人工判断的一律 keep，不臆造。

## 输出

只输出一个 JSON 对象：

{"items": [{"kind": "conflict", "id": "C1", "action": "auto", "winner": "R5", "quote": "材料原文片段"},
            {"kind": "conflict", "id": "C2", "action": "keep"},
            {"kind": "gap", "id": "G3", "action": "close", "quote": "材料原文片段"}]}
