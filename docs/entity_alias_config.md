# 设备别名持久化配置

## 1. 目的
通过配置文件为实体绑定稳定显示名与别名，解决：
- 设备名里包含 `None`、乱码、冗长前缀
- 多路同名设备不易区分
- 自然语言里常用叫法与实体名不一致

## 2. 配置文件位置
默认读取：
- `data/entity_aliases.json`

可通过环境变量覆盖：
```bash
export SMARTHOME_ENTITY_ALIAS_FILE=/path/to/entity_aliases.json
```

参考模板：
- `data/entity_aliases.example.json`

## 3. 配置格式
```json
{
  "entity_overrides": {
    "switch.demo_socket_1": {
      "name": "客厅排插",
      "aliases": ["一号插座", "客厅插座一号"]
    },
    "switch.demo_socket_2": {
      "name": "客厅排插",
      "aliases": ["二号插座", "客厅插座二号"]
    }
  }
}
```

字段说明：
- `name`：覆盖显示名称（UI 和实体候选名）
- `aliases`：附加可匹配别名（用于实体匹配和列表展示）

## 4. 生效规则
- 运行时按文件修改时间自动重载，不需要重启进程。
- `name` 会先做清洗（去除 `None/null` 等噪声词）。
- 当多个实体最终 `name` 相同，接口会自动展示为 `第1路/第2路` 进行消歧。

## 5. 验证方法
```bash
curl -sS 'http://127.0.0.1:8000/api/v1/entities?limit=50'
```
检查返回项：
- `name` 是否为期望显示名（含第N路）
- `aliases` 是否包含你配置的别名
