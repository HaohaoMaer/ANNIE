# Design: 记忆 / 历史层重构 + 压缩职责明晰

## 压缩/记忆总览（重构后）

```
┌─────────────────────────────────────────────────────────────────┐
│                    LLM message list (单次 Executor 调用)            │
├─────────────────────────────────────────────────────────────────┤
│ SystemMessage                                                    │
│   <character>/<world_rules>/<situation>  [静态]                    │
│   <memory_categories>                    [常量]                    │
│   <working_memory>   ← MemoryAgent.build_context(input_event)      │
│   <todo>             ← render_todo_text(memory)                    │
│   <available_skills> [静态]                                         │
│ + history_msgs       ← HistoryStore.read_last(N)（未折叠条目）       │
│ + HumanMessage(trigger)                                            │
│ + AIMessage/ToolMessage 累积                                        │
└─────────────────────────────────────────────────────────────────┘
           │                                       │
           ▼                                       ▼
   ContextBudget.check                     ToolAgent.micro
   (messages 接近模型上限时                 (单条 ToolMessage
    emergency-fold 最早轮次)                  超 2000 字符时头尾截断)
```

```
┌───────────────────────┬──────────────────────────────────────┐
│   JSONL (HistoryStore)│   Vector DB (MemoryInterface)         │
├───────────────────────┼──────────────────────────────────────┤
│ 对话原文 + 顺序        │ reflection / semantic / impression    │
│ 永远写入                │ / todo                               │
│ 不被折叠 stub 污染      │ (不再写 episodic)                     │
│                       │                                      │
│ 折叠 = 读 JSONL 未折叠 │ 折叠 = 写一条 impression               │
│   部分的 summary 摘要   │                                      │
│                       │                                      │
│ WorldEngine 决策 prune │ content hash 去重 (semantic /        │
│   何时触发 + 保留多少    │   reflection)                        │
└───────────────────────┴──────────────────────────────────────┘
```

## 关键决策

### D1. 为什么向量库不再存 episodic

**问题**：同一句对话 = JSONL 一条 + 向量库 episodic 一条；Reflector 会再抽成 reflection/semantic；折叠会再抽成 impression。同一事实在向量库以三种粒度重复。recall 命中同一信息的多个视角，token 被稀释。

**候选**：
- (a) 保持现状，recall 时按 category 权重过滤
- (b) episodic 只写"外部输入"（玩家/其他 NPC），NPC 自己的 response 不写
- (c) 完全不写 episodic，向量库只存提炼物 ← 选这个

**为何选 (c)**：(a) 只是把问题挪到读取侧；(b) 规则复杂、边界模糊。对话顺序/原文在 JSONL 已有权威来源，向量库唯一专长是"语义召回"，应该只放提炼物。需要原话时下层提供 grep JSONL 即可。

### D2. 为什么折叠不改写 JSONL

**问题**：当前 `replace(turn_ids, folded_stub)` 让 JSONL 里出现 `[folded]` 前缀条目，既占 history context 又和 impression 的内容重复。

**选择**：JSONL 只追加不修改；折叠只向向量库写一条 impression。用 `last_folded_turn_id` 游标记录进度。

**副作用**：JSONL 体积不再因折叠减小 → 引出 D3。

### D3. JSONL 淘汰交给 WorldEngine

**选择**：`HistoryStore.prune(keep_last=N | before_turn_id=X)` 作为原语；HistoryStore 不知道什么是"游戏时间"或"场景"；策略（比如"每次场景切换清理旧的"/"保留最后 500 条"）由 WorldEngine 决定。

**为何两个原语都提供**：
- `before_turn_id=X`：世界引擎按游戏时间算出 turn_id 分界（最通用）
- `keep_last=N`：小项目/默认实现不想算分界的便利入口

两者互斥（同时指定报错）。

### D4. 折叠 cursor 的持久化

三个选项：
- (a) HistoryStore 的 metadata 区（新开 `.meta.json` 同目录文件）
- (b) 在 JSONL 头部插入一条特殊条目
- (c) Compressor 自己管，放 `{history_dir}/.fold_cursor/{npc_id}.txt`

**选 (a)**：HistoryStore 本来就拥有路径，新增一个 sidecar JSON 是最小侵入；(b) 污染 JSONL 语义；(c) 让 Compressor 知道目录结构违反分层。

### D5. 去重用 upsert 还是 grep-then-add

**选 upsert + 稳定 id**：ChromaDB 原生支持。相同 content hash 即覆盖——唯一副作用是"重复的 fact 会刷新 timestamp"，通常是期望行为（"这件事最近又被提了"）。

**不选** grep-then-add：每次写都多一次查询，reflector 高频写入下代价明显。

**为何只 semantic + reflection**：
- episodic：本 change 已取消写入
- impression：同文本概率近零，强制去重反而会丢时间段
- todo：每次 add 本就允许重复意图（"再去厨房一次"）

### D6. person 纳入 hash 的理由

`relationship_note` 被并入 reflection category，以 `metadata.person` 区分目标人物。同一观察语句写给不同人物语义不同（"她信任 X" vs "她信任 Y"）。hash 必须包含 person 否则会互相覆盖。

```python
def _dedup_id(category, content, metadata):
    person = metadata.get("person", "")
    return sha1(f"{category}|{content}|{person}".encode()).hexdigest()[:16]
```

### D7. 检索去重的作用域

**选 run-scoped**：`_recall_seen_ids: set[str]` 放 `AgentContext.extra`，随 run 生命周期消亡。

**不选**：
- 跨 run 去重——LLM 需要多次看到相同记忆来强化记忆，跨 run 去重会伤到这点。
- 完全去重所有工具返回——有时 LLM 故意对同一查询换角度问，去重会"骗"它拿到空结果。只过滤"已在 `<working_memory>` 中展示过的"这一类最冗余的情况即可。

### D8. Compressor 与 ContextBudget 不合并

它们表面都叫"压缩"，实际是两个维度：

| 维度       | Compressor                   | ContextBudget                 |
|------------|------------------------------|-------------------------------|
| 数据寿命   | 跨 run 持久化                | 单次 Executor loop            |
| 触发时机   | `handle_response` 末尾        | 每步 LLM 调用前                |
| 输出位置   | impression 记忆 + JSONL cursor | messages 列表里一条 summary    |
| 目的       | 长期遗忘 / 主题化             | 避免超模型上下文限制           |

合并会让"遗忘"和"上下文裁剪"纠缠，反而更难解释。CLAUDE.md 需用上述表格更新。

## 数据迁移

- **向量库中现有 episodic 记录**：保留不动。`memory.recall` 仍能返回；只是不再新写入。下游代码不主动依赖 episodic 类别，不需要迁移脚本。
- **JSONL 中现有 `is_folded=True` stub**：读取时跳过，不渲染进 history_msgs。新 append 不再产生。字段本身保留一两个 release 后再彻底删除。
- **folded_cursor 的初始值**：对已有 NPC，首次启动时游标设为 JSONL 中最大的 folded stub 的 turn_id（若存在），否则 0。

## 风险与折中

1. **去掉 episodic 后，"角色精确回忆原话"的能力变弱**：impression 是摘要，不保留措辞。接受此 tradeoff，后续若出现"NPC 需要引用原话"的业务需求，开 `history_grep` 工具即可（本 change 不做）。
2. **upsert 导致 timestamp 被刷新**：同一事实的 metadata 会反映最近一次 reflector 的时间，非首次出现时间。讨论后认为"最近出现"比"首次出现"更贴合 NPC 主观感受。如需首次时间，reflector 可在 metadata 里额外塞 `first_seen`（本 change 不做）。
3. **prune 截断的那一段原话彻底丢失**：若 prune 之前没被 Compressor 折叠过，对话原文真的消失（只剩 Reflector 阶段抽出的 semantic/reflection）。约定：WorldEngine 调 prune 前应确保该范围的 turn 已被折叠（封装在 `prune_safe` helper 里是后续可选）。
4. **去重导致测试意图被掩盖**：unit test 里故意连写两次相同 fact 以验证"两条"的假设会失败。这类测试需要更新为验证"一条"。
