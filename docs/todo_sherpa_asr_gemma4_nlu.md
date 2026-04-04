# TODO: sherpa-asr + Gemma 4 NLU 对接落地清单（v1）

## 1. 目标与边界
- 保留 `sherpa-asr-android` 作为 ASR（端侧）。
- 新增 `Gemma 4` 作为 NLU（意图 + 槽位 + 工具调用 JSON）。
- 维持现有执行链路：`/api/v1/command`、`/api/v1/confirm`、HA 工具执行不大改。
- 目标是“最稳工程路径”：先可用、再优化。

## 2. 架构决策
- 主链路：`Android(ASR final text) -> /api/v1/nlu/parse -> Executor -> HA`。
- NLU 输出必须是严格 JSON，不允许自由文本混出。
- 无网兜底：端侧规则引擎仅覆盖高频命令（开关灯、亮度、温度）。

## 3. JSON 契约（必须先定）
- [ ] 定义并冻结 `NLUResult` schema。
- [ ] 字段最小集：`intent`、`slots`、`tool_calls`、`need_confirmation`、`confidence`、`reply_text`。
- [ ] 增加 schema 校验失败错误码：`NLU_SCHEMA_INVALID`。
- [ ] 增加工具白名单校验，拒绝未授权 `tool_calls`。

## 4. 后端任务（Gemma 4 NLU）
- [ ] 新增 `POST /api/v1/nlu/parse`。
- [ ] 实现 Prompt 模板（系统约束 + few-shot）。
- [ ] 实现模型输出 JSON 解析与自动重试（最多 1 次修复重试）。
- [ ] 做槽位归一化：房间别名、设备别名、数值单位。
- [ ] 打点：`intent_acc`、`slot_f1`、`latency_ms`、`confirm_rate`。

## 5. Android 任务（ASR 保持不变）
- [ ] 将主请求从旧文本解析接口切到 `/api/v1/nlu/parse`。
- [ ] 保持确认流：`need_confirmation=true` 时走 `/api/v1/confirm`。
- [ ] 增加无网 fallback 开关（仅高频命令）。
- [ ] 增加端侧日志字段：`trace_id`、`asr_final_text`、`nlu_latency`。

## 6. 质量与验收
- [ ] 意图准确率 `>= 95%`（家庭高频指令集）。
- [ ] 槽位 F1 `>= 90%`。
- [ ] 端到端 P95 `<= 2.0s`（ASR + NLU + 执行）。
- [ ] 高风险操作确认覆盖率 `= 100%`。
- [ ] 失败可分类：`ENTITY_NOT_FOUND`、`FORBIDDEN`、`UPSTREAM_TIMEOUT`、`NLU_SCHEMA_INVALID`。

## 7. 里程碑
- [ ] M1（1-2 天）：`/nlu/parse` + schema + 基础可跑通。
- [ ] M2（2-3 天）：Android 接入 + confirm 流回归。
- [ ] M3（2 天）：评测集回放、参数调优、发布候选。

## 8. 当前优先级（Next Action）
- [ ] 先落地 `NLUResult` schema 与 `POST /api/v1/nlu/parse` 空实现（mock 返回）。
- [ ] 补 20~50 条中文家居指令 few-shot 样例并入库。
