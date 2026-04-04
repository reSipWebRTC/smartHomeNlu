# SmartHome NLU 架构流程图与数据流图

## 1. 高层架构流程图（管理/评审）
```mermaid
flowchart LR
    U[用户语音] --> A[手机端 ASR]
    A --> B[主服务 Runtime]
    B --> C[主路 NLU\nTinyBERT ONNX v1]
    C --> D{置信度是否足够}
    D -->|是| E[策略校验 + 执行]
    D -->|否| F[兜底 NLU\nQwen2.5-1.5B 远程]
    F --> E
    E --> G[Home Assistant]
    G --> H[结果返回客户端]
```

## 2. 详细工程流程图（开发联调）
```mermaid
flowchart TB
    subgraph Client["客户端（Android）"]
        U[Mic 输入]
        ASR[sherpa-asr-android]
        APP[UI/播报]
    end

    subgraph Runtime["主流程机 Runtime"]
        API[FastAPI\n/api/v1/command\n/api/v1/confirm\n/api/v1/nlu/parse]
        DST[DST 会话状态]
        REDIS[(Redis\nsession/history)]
        ROUTER[NLU Router]
        MAIN[TinyBERT ONNX v1\nmain_onnx]
        FALLBACK_RULE[rule fallback]
        ENTITY[实体解析/槽位继承]
        POLICY[风险策略引擎]
        EXEC[执行器]
        ADAPTER[HA Adapter\nha_gateway / ha_mcp]
        BUS[EventBus/审计日志]
    end

    subgraph Edge["边缘机 Mac mini (192.168.3.44)"]
        QWEN[Ollama\nQwen2.5-1.5B]
    end

    subgraph HA["Home Assistant"]
        HACORE[HA Core]
    end

    U --> ASR --> API
    API <--> DST
    DST <--> REDIS

    API --> ROUTER
    ROUTER --> MAIN
    ROUTER -->|主路低置信| QWEN
    QWEN --> ROUTER
    ROUTER -->|远程失败/超时| FALLBACK_RULE

    ROUTER --> ENTITY --> POLICY
    POLICY -->|需确认| API
    POLICY -->|通过| EXEC --> ADAPTER --> HACORE
    HACORE --> ADAPTER --> EXEC --> API

    API --> BUS
    EXEC --> BUS
    API --> APP
```

## 3. 数据流图（DFD-L1）
```mermaid
flowchart TB
    E1[外部实体: 客户端 App]
    E2[外部实体: 远程 Qwen 服务]
    E3[外部实体: Home Assistant]

    P1((P1 API 接入))
    P2((P2 会话上下文处理))
    P3((P3 NLU 路由与解析))
    P4((P4 风险策略判定))
    P5((P5 工具执行与回写))

    D1[(D1 Redis\nSession/History)]
    D2[(D2 ONNX 模型资产\nmodel.onnx/labels/vocab)]
    D3[(D3 审计事件日志)]

    E1 -->|text, session_id, user_id| P1
    P1 -->|session query/update| P2
    P2 <--> D1

    P1 -->|utterance + context| P3
    P3 <--> D2
    P3 -->|fallback request| E2
    E2 -->|intent/sub_intent/slots/confidence| P3

    P3 -->|NLUResult| P4
    P4 -->|confirm_required / deny / allow| P1
    P4 -->|approved action| P5

    P5 -->|control/query| E3
    E3 -->|execution result| P5
    P5 -->|history write| D1
    P5 -->|audit events| D3
    P5 -->|final response payload| P1
    P1 -->|JSON response| E1
```

## 4. 说明
- 主路优先：`TinyBERT ONNX v1` 承担低延迟高频意图识别。
- 兜底触发：主路低置信或异常时调用远程 `Qwen2.5-1.5B`。
- 最终动作必须经过策略层校验，高风险操作进入确认流程。
- 数据闭环落到 Redis 与审计日志，支持回放、排障与指标统计。
