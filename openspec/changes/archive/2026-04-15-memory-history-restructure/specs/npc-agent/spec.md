# NPC Agent Spec Delta — memory-history-restructure

## ADDED Requirements

### Requirement: 一次 run 内，向 LLM 展示过的记忆记录不重复出现

NPCAgent 在一次 `run()` 内维护一个"已向 LLM 展示的记忆 id 集合"，作用域限定本次 run：

- `MemoryAgent.build_context` 计算 `<working_memory>` 时把返回记录的 id 灌入集合
- `MemoryRecallTool` / `MemoryGrepTool` 的返回值在渲染前过滤掉已在集合中的 id；新 id 加入集合

此去重只在本 run 生效，跨 run 的重复召回不受影响（以保留"多次出现强化记忆"的效果）。

#### Scenario: working_memory 与工具调用不重复同一记录

- **WHEN** run 开始时 `build_context` 已把记录 A 纳入 `<working_memory>`
- **AND** 本 run 内 LLM 调用 `memory_recall` 返回的结果中包含记录 A
- **THEN** 工具返回给 LLM 的 records 列表中不含 A
- **AND** records 列表中的其他记录正常返回

#### Scenario: 去重不跨 run

- **WHEN** run1 已向 LLM 展示记录 A；run2 启动
- **THEN** run2 的 `<working_memory>` 或工具响应中可以再次出现 A

---

## REMOVED Requirements

### Requirement: ContextCompressor 五档压缩

**Reason**: 五档压缩器（snip/microcompact/collapse/autocompact/reactive）从未被 NPCAgent 主流程引用，属实现未接入的遗留。其职责已被 `ContextBudget`（Executor 内部 emergency fold）与 `Compressor`（WorldEngine 侧对话折叠）分别承担。

**Migration**: 无——无外部调用方。删除 `src/annie/npc/context_manager.py` 即可。

### Requirement: ImmediateMemory 即时工作记忆层

**Reason**: 设计时预留的"类 Claude Code MEMORY.md 指针层"从未被接入 Executor 或任何 prompt 渲染路径。当前 `<working_memory>` 由 `MemoryAgent.build_context` 直接从 MemoryInterface 拉取，不经过 ImmediateMemory。

**Migration**: 无——无外部调用方。删除 `src/annie/npc/memory/immediate_memory.py` 即可。
