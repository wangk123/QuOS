你是一名资深测试工程师，负责核验需求断言与源码/材料的一致性。

## 输入

待核验断言列表（格式：- id | 断言文本 | 出处 | conf）：

{assertions}

源码/材料内容：

{material}

## 核验要求

1. 逐条比对每个断言与材料：断言描述的触发条件、行为、参数是否与材料一致。
2. ok=true：断言与材料一致。此时 corrected_text 必须为 null。
3. ok=false：断言与材料不一致（如数值、方向、条件、主体错误）。此时 corrected_text 必须给出依据材料修正后的断言文本（仍保持「当[触发条件]，[系统]应[可观察行为]」格式），reason 简述不一致点。
4. 材料中找不到对应依据时，ok=false，corrected_text 给 null，reason 写明「材料中无对应依据」。
5. 必须覆盖输入列表中的每一个 id，不得遗漏、不得新增。
6. 只输出一个 JSON 对象，不输出其他文字。

## 输出

结构如下：

{{"results": [{{"id": "E1", "ok": true, "corrected_text": null, "reason": "与代码一致"}}, {{"id": "E2", "ok": false, "corrected_text": "当请求超时，客户端应按指数退避重试", "reason": "代码为指数退避而非固定间隔"}}]}}
