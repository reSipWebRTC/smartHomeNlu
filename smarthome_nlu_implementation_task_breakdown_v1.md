# SmartHome NLU 实施任务拆解

## 文档信息
- 版本：v1.0
- 日期：2026-04-03
- 输入文档：
  - `smarthome_nlu_architecture_module_design_v1.md`
  - `smarthome_nlu_module_interface_checklist_v1.md`
- 目标：把架构设计拆解为可执行任务包，明确依赖、产出、验收

## 1. 交付目标
1. 上线运行时最小闭环：文本指令 -> NLU -> ha_gateway -> 设备执行 -> 回执。
2. 建立安全基线：RBAC、二次确认、幂等、审计。
3. 建立离线迭代闭环：难例回流 -> 训练 -> 评测门禁 -> 发布。

## 2. 团队角色建议
| 角色 | 职责 |
|---|---|
| 架构/Tech Lead | 技术方案、关键评审、风险把控 |
| 平台工程 | 网关、配置、CI/CD、监控告警 |
| NLU 工程 | 主路模型、兜底模型、路由策略 |
| 执行层工程 | entity resolver、policy、executor、ha_gateway adapter |
| MLOps 工程 | 数据流水线、蒸馏训练、评测门禁、模型注册 |
| QA | 接口测试、回归测试、端到端验证 |

## 3. 里程碑与排期（建议 14 周）

| 阶段 | 周期 | 目标 | 里程碑 |
|---|---|---|---|
| Phase 0 | 第 1 周 | 工程底座就绪 | CI/CD、配置中心、日志追踪完成 |
| Phase 1 | 第 2-4 周 | 在线最小闭环 | `api-gateway + nlu-main + executor` 可控灯光 |
| Phase 2 | 第 5-6 周 | 安全与策略上线 | RBAC/确认/幂等/重试/审计生效 |
| Phase 3 | 第 7-8 周 | 兜底路与多轮增强 | `nlu-fallback + dst` 稳定运行 |
| Phase 4 | 第 9-11 周 | 离线飞轮打通 | 难例回流 -> 蒸馏 -> gate -> registry |
| Phase 5 | 第 12-14 周 | 稳定化与发布 | Shadow、灰度、回滚预案验证 |

## 4. 任务拆解（WBS）

## 4.1 Phase 0：工程底座

| ID | 任务 | Owner | 估算（人天） | 依赖 | 产出 |
|---|---|---|---:|---|---|
| P0-01 | 仓库结构初始化（runtime/offline/shared） | 平台工程 | 2 | - | Monorepo 目录与模板 |
| P0-02 | 统一配置管理（env + secret） | 平台工程 | 2 | P0-01 | 配置加载组件 |
| P0-03 | CI 流水线（lint/test/build） | 平台工程 | 2 | P0-01 | CI 工作流 |
| P0-04 | tracing/logging 规范落地 | 平台工程 | 2 | P0-01 | `trace_id` 贯穿样例 |
| P0-05 | 基础观测面板与告警 | 平台工程 | 2 | P0-04 | Dashboard v1 |

## 4.2 Phase 1：在线最小闭环

| ID | 任务 | Owner | 估算（人天） | 依赖 | 产出 |
|---|---|---|---:|---|---|
| P1-01 | `api-gateway` 外部接口实现 | 平台工程 | 3 | P0-* | `/api/v1/command` |
| P1-02 | `nlu-main` 推理服务封装 | NLU 工程 | 4 | P0-* | `/internal/v1/nlu/main/predict` |
| P1-03 | `nlu-router` 路由逻辑实现 | NLU 工程 | 3 | P1-02 | `/internal/v1/nlu/route` |
| P1-04 | `entity-resolver` 基础映射实现 | 执行层工程 | 4 | P1-01 | `/internal/v1/entity/resolve` |
| P1-05 | `ha-gateway-adapter` 封装 | 执行层工程 | 3 | P1-04 | `/internal/v1/ha/service-call` |
| P1-06 | `executor` 最小编排链路 | 执行层工程 | 4 | P1-05 | `/internal/v1/executor/run` |
| P1-07 | `response-service` 回执模板 | 执行层工程 | 2 | P1-06 | `/internal/v1/response/render` |
| P1-08 | E2E 场景联调（开关灯） | QA | 3 | P1-01..07 | 最小闭环验收报告 |

## 4.3 Phase 2：安全与策略

| ID | 任务 | Owner | 估算（人天） | 依赖 | 产出 |
|---|---|---|---:|---|---|
| P2-01 | `policy-engine` RBAC 白名单 | 执行层工程 | 3 | P1-06 | `/policy/evaluate` |
| P2-02 | 二次确认流程（start/commit） | 执行层工程 | 3 | P2-01 | `/policy/confirm/*` |
| P2-03 | 幂等键与去重窗口 | 执行层工程 | 2 | P2-01 | Redis 去重机制 |
| P2-04 | 重试策略与错误分类 | 执行层工程 | 2 | P2-03 | 可重试矩阵 |
| P2-05 | 审计日志落盘与字段校验 | 平台工程 | 3 | P0-04 | 审计日志服务 |
| P2-06 | 安全回归测试（P0/P1 指令） | QA | 3 | P2-01..05 | 安全测试报告 |

## 4.4 Phase 3：兜底路与多轮增强

| ID | 任务 | Owner | 估算（人天） | 依赖 | 产出 |
|---|---|---|---:|---|---|
| P3-01 | `nlu-fallback` 推理服务接入 | NLU 工程 | 4 | P1-03 | `/internal/v1/nlu/fallback/predict` |
| P3-02 | JSON Grammar 强约束 | NLU 工程 | 2 | P3-01 | 100% 可解析输出 |
| P3-03 | `dst-service` 会话存储接口 | NLU 工程 | 3 | P1-03 | `/dst/session/*` |
| P3-04 | 槽位继承与指代消解 | NLU 工程 | 3 | P3-03 | 多轮逻辑 |
| P3-05 | 低置信澄清策略 | NLU 工程 | 2 | P3-01..04 | 澄清流程 |
| P3-06 | 多轮 E2E 回归测试 | QA | 3 | P3-01..05 | 多轮测试报告 |

## 4.5 Phase 4：离线飞轮

| ID | 任务 | Owner | 估算（人天） | 依赖 | 产出 |
|---|---|---|---:|---|---|
| P4-01 | `hard-example-collector` Worker | MLOps 工程 | 3 | P2-05 | `evt.data.hard_example.v1` |
| P4-02 | `data-pipeline`（脱敏/去重/切分） | MLOps 工程 | 4 | P4-01 | 数据集产物 |
| P4-03 | `teacher-labeling` 批处理接口 | MLOps 工程 | 3 | P4-02 | 标注数据产物 |
| P4-04 | `distill-trainer` 增量训练任务 | MLOps 工程 | 4 | P4-03 | 候选模型 |
| P4-05 | `eval-gate` 门禁流水线 | MLOps 工程 | 4 | P4-04 | Gate 结果 |
| P4-06 | `model-registry` 注册与发布 | MLOps 工程 | 3 | P4-05 | 版本发布能力 |
| P4-07 | 离线闭环端到端演练 | QA | 3 | P4-01..06 | 离线闭环报告 |

## 4.6 Phase 5：稳定化与发布

| ID | 任务 | Owner | 估算（人天） | 依赖 | 产出 |
|---|---|---|---:|---|---|
| P5-01 | 压测与容量评估 | 平台工程 | 3 | P3-* | 压测报告 |
| P5-02 | Shadow 测试框架 | MLOps 工程 | 3 | P4-05 | Shadow 报告 |
| P5-03 | 灰度策略与回滚演练 | 平台工程 | 3 | P4-06 | 回滚预案验证 |
| P5-04 | 生产发布 Runbook | Tech Lead | 2 | P5-01..03 | Runbook 文档 |
| P5-05 | 发布前总验收 | QA | 2 | 全阶段 | UAT 报告 |

## 5. 关键依赖关系
1. `P0` 是全部阶段前置。
2. `P1` 完成后才能进入 `P2/P3`。
3. `P4` 依赖在线链路稳定事件输出（尤其审计与执行结果事件）。
4. `P5` 必须以 `P3 + P4` 双完成为前提。

## 6. 验收标准（DoD）

## 6.1 功能 DoD
1. 在线路径可稳定处理 CONTROL/QUERY/SCENE 三类核心意图。
2. 高风险指令必须经过确认接口才可执行。
3. 重复控制请求在去重窗口内不重复执行。
4. 失败请求可按错误分类正确降级或追问。

## 6.2 质量 DoD
1. `nlu-main` P99 < 50ms。
2. `nlu-fallback` P99 < 800ms（GPU）。
3. 端到端 P99 < 1200ms。
4. `nlu-fallback` JSON 解析成功率 = 100%。
5. 在线设备执行成功率 > 98%。

## 6.3 流程 DoD
1. Gate 失败自动阻断发布。
2. Shadow 差异率超阈值自动阻断。
3. 生产可一键回滚到上一个稳定版本。

## 7. 风险与缓解
| 风险 | 影响 | 缓解措施 |
|---|---|---|
| 实体解析误匹配 | 高 | 引入候选阈值 + 澄清追问 + 别名词典 |
| 兜底模型延迟波动 | 中 | GPU 常驻优先，CPU 仅兜底，超时降级规则 |
| 高风险指令误执行 | 高 | 二次确认 + RBAC + 幂等去重 |
| 数据污染导致评测虚高 | 高 | 固定测试集 + MinHash 去重 + Gate 阻断 |
| ha_gateway 上游异常 | 中 | 重试矩阵 + 保护模式 + 降级路径 |

## 8. 发布清单（Go-Live Checklist）
1. 接口联调通过（接口清单 100% 覆盖）。
2. 安全策略通过（RBAC/确认/审计）。
3. 压测与容量报告通过。
4. Shadow + 灰度通过。
5. 回滚演练通过。
6. Runbook 与值班表就绪。
