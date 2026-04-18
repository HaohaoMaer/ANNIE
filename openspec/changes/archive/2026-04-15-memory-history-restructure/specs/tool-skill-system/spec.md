# Tool & Skill System Spec Delta — memory-history-restructure

## MODIFIED Requirements

### Requirement: plan_todo 工具提供幂等的 complete 与带元数据的 list

`plan_todo` built-in tool 在原有 `add / complete / list` 基础上强化：

- `add(content)` 在 metadata 中写入 `created_at`（ISO8601 UTC）与 `todo_id`。
- `complete(todo_id)` 调用前必须校验该 id 存在且状态为 open；否则返回 `{"success": False, "error": "unknown or already closed"}` 且不写任何记录。
- `list()` 返回项包含 `{todo_id, content, timestamp}`，按 `timestamp` 倒序（最新在前）。

#### Scenario: complete 未知 id 不写记录

- **WHEN** 对一个不存在的 todo_id 调用 `plan_todo(complete)`
- **THEN** 工具返回 `{"success": False, "error": ...}`
- **AND** 向量库 `todo` 类别下没有新增 closed 记录

#### Scenario: complete 已关闭 id 失败

- **WHEN** 同一 todo_id 被 `complete` 两次
- **THEN** 第二次返回失败且不写记录

#### Scenario: list 带元数据且倒序

- **WHEN** 先后 `add("A")` 与 `add("B")` 两个 todo
- **THEN** `list()` 返回顺序为 `[B, A]`
- **AND** 每项含 `todo_id / content / timestamp` 三字段
