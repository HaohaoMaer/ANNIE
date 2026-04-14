# World Engine Capability Spec — Delta

本次 change 对 world-engine capability 的修订。

## ADDED Requirements

### Requirement: WorldEngine 必须持有 per-NPC 的 HistoryStore

每个由 WorldEngine 管理的 NPC 有独立的对话历史存储：

- 单 NPC 单 JSONL 文件：`./data/history/{npc_id}.jsonl`
- 条目结构含 `turn_id` / `timestamp` / `speaker` / `content` / `is_folded` / `folded_from`
- 支持 append、按 turn_id 范围切片、token 估算、批量替换（Fold 用）

#### Scenario: handle_response 追加 history

- **WHEN** WorldEngine.handle_response(npc_id, resp) 被调用
- **THEN** resp.dialogue 作为新 HistoryEntry append 到该 NPC 的 JSONL
- **AND** turn_id 单调递增

#### Scenario: build_context 渲染 history

- **WHEN** WorldEngine.build_context(npc_id, event)
- **THEN** HistoryStore 读取最后 MAX_HISTORY_TURNS 条
- **AND** FoldedEntry 和原始 turn 都按时间序渲染为 AgentContext.history

---

### Requirement: WorldEngine 必须持有 Compressor 并在 handle_response 中触发 Fold

Compressor 封装 Trim / Fold 逻辑，依赖 HistoryStore + MemoryBackend + LLM：

- `Compressor.maybe_fold(npc_id)` 在 handle_response 末尾调用
- token 阈值超过 FOLD_TOKEN_THRESHOLD 时选取最旧的未折叠段送主 LLM 摘要
- 产物双写：替换 HistoryStore 对应段落 + memory.remember(category="impression")
- is_folded=True 的 entry 不再进入 Fold 候选集

#### Scenario: Fold 在 handle_response 末尾触发

- **WHEN** handle_response 追加 history 后 token 超阈值
- **THEN** Compressor.maybe_fold 被调用
- **AND** Fold 完成前 handle_response 不返回

#### Scenario: 主 LLM 复用

- **WHEN** Compressor 需要摘要
- **THEN** 使用 WorldEngine 持有的同一个 LLM 实例
- **AND** 不引入额外 LLM 依赖

---

## MODIFIED Requirements

### Requirement: WorldEngine.build_context 生成 AgentContext 的标准步骤

原需求"WorldEngine 必须实现 build_context / handle_response / memory_for"升级为明确步骤：

1. 组装 character_prompt（从 NPCProfile）
2. 叠加 world_rules（从场景配置）
3. 渲染 history（HistoryStore 经 Trim 后）
4. 构造 MemoryInterface（绑定 per-NPC collection）
5. **不做情景预取**——长期记忆的召回交给 Agent 内部的 tool-use loop

#### Scenario: 不做预召回

- **WHEN** WorldEngine.build_context 执行
- **THEN** 不调用 memory.recall 预取记忆
- **AND** AgentContext 中不含预填充的 memory 字段，只提供 MemoryInterface 实例

#### Scenario: handle_response 的标准化步骤

- **WHEN** WorldEngine.handle_response(npc_id, resp) 执行
- **THEN** 按序完成：
  1. resp.dialogue → HistoryStore.append(category=episodic metadata 同步写 memory)
  2. resp.reflection → memory.remember(category="reflection")
  3. resp.memory_updates → memory.remember(各自 category)
  4. Compressor.maybe_fold(npc_id)
- **AND** 任一步失败不影响已完成步骤的持久化
