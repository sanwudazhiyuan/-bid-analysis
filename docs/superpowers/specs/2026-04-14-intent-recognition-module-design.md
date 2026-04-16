# 社保自助机意图识别模块 · 设计文档

- 日期：2026-04-14
- 作者：Claude + 用户协作设计
- 状态：待实施

## 1. 背景与目标

重庆社保自助机（便携设备）项目需要为语音/文字输入添加一层**意图识别服务**，把用户的自然语言映射到界面菜单树上的某一个业务选项。

意图识别范围限定为**用户手册第三章**描述的菜单界面：

- **一级菜单（1 个）**：制卡程序主页，包含 7 项业务入口。
- **二级菜单（1 套，共享）**：点击一级菜单中"新制卡"或"补换卡"后进入，包含 8 项"社会保障卡 xxx"子业务。
- 其余一级菜单项（挂失、解挂、信息查询、修改/重置密码）无二级菜单，由界面模块直接进入对应业务流程。
- 业务流程内部的细节操作（读卡、人脸识别、填写信息等）**不在本模块识别范围**。

模型：`qwen3.5:4b`（用户本地已有的 Ollama 模型 tag）。

## 2. 功能范围

### In scope
- 给定用户的一句话 + 当前所在菜单节点，返回最匹配的子菜单 intent ID 与名称。
- 菜单结构通过人工维护的 YAML 配置文件定义（不从 docx 手册自动解析）。
- 识别失败时返回 `unknown`，由调用方决定后续追问策略。
- 服务作为独立的 HTTP 微服务，Docker 部署。
- 两个 REST endpoint 分别服务"更新当前菜单状态"和"识别用户意图"两类调用方。

### Out of scope
- 全局导航意图（"返回上一页"、"回首页"等）——由界面模块自己处理，不走意图识别。
- 置信度阈值控制——不输出也不拦截。
- Few-shot 示例——prompt 仅用菜单元数据。
- 业务流程内操作的意图识别（见 §1）。
- 用户会话并发——便携机单用户场景，服务端采用全局单例状态。
- Ollama 自身的部署与配置——由用户独立维护，本模块只通过 `OLLAMA_URL` 环境变量与之对接。

## 3. 技术方案概览

采用 **Prompt + Ollama structured output（JSON Schema 约束）+ 服务端白名单校验**的三层稳定性策略：

1. **Prompt 层**：system prompt 里显式列出当前候选菜单的 `id / name / description / keywords`，告诉模型"只能从这些 id 中选或返回 unknown"。
2. **解码约束层**：调用 Ollama `/api/chat` 时传入动态构造的 JSON Schema，把 `intent_id` 字段的 `enum` 限制为当前候选 ID 列表 + `"unknown"`。Ollama 会做 grammar-constrained decoding，从物理层面杜绝幻觉 ID。
3. **校验兜底层**：服务端收到响应后再做一次白名单校验，防止 Ollama 版本对 structured output 支持不完整时降级失效。命中非法值一律归为 `unknown`。

拒绝了两种备选方案：
- 纯 prompt 无 schema：4b 小模型易幻觉出不存在的 ID。
- Embedding 检索 + LLM 仲裁：本场景候选最多 8 项，过度工程。

## 4. 组件结构

```
intent-service/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口，注册路由、启动时校验 YAML
│   ├── api.py               # 两个 endpoint 的 handler
│   ├── state.py             # 全局单例：当前菜单 ID
│   ├── menu.py              # 加载 YAML、构建菜单树、查候选、白名单校验
│   ├── recognizer.py        # 调 Ollama（prompt + schema + 解析 + 兜底）
│   ├── schemas.py           # pydantic 请求/响应模型
│   └── config.py            # 环境变量读取
├── config/
│   └── menus.yaml           # 菜单树定义
├── tests/
│   ├── test_menu.py
│   ├── test_recognizer.py
│   └── test_api.py
├── Dockerfile
├── docker-compose.yml       # 仅 intent-service 一项
├── requirements.txt
└── README.md
```

### 组件职责

| 组件 | 职责 | 依赖 |
|---|---|---|
| `menu.py` | 启动时加载并校验 `menus.yaml`；`get(id)` / `get_candidates(id)` / `is_valid_id(id)` | yaml 文件 |
| `state.py` | 全局单例 `current_menu_id: str`，默认 `"root"`；`get()` / `set(id)` | 无 |
| `recognizer.py` | `recognize(text, candidates) -> IntentResult`；内部构造 schema、调 ollama、解析 JSON、白名单兜底 | httpx |
| `api.py` | 两个 endpoint 薄胶水层 | 上述三者 |
| `schemas.py` | 请求/响应的 pydantic 模型 | — |
| `config.py` | 读取 `OLLAMA_URL` / `MODEL_NAME` / `MENU_FILE` / `TEMPERATURE` | 环境变量 |

设计原则：
- `menu.py` / `state.py` / `recognizer.py` 不依赖 FastAPI，可独立单测。
- `api.py` 零业务逻辑，纯粘合。
- 将来更换 LLM 引擎（例如换 vLLM）只需修改 `recognizer.py`。

## 5. API 契约

两个 endpoint 对应两类调用方，各自独立。

### 5.1 更新当前菜单状态（界面模块调用）

```
POST /state/menu
```

**Request**
```json
{ "menu_id": "new_card" }
```

**Response 200**
```json
{ "menu_id": "new_card", "menu_name": "新制卡" }
```

**Response 404（menu_id 非法）**
```json
{ "error": "unknown_menu_id", "menu_id": "foo" }
```

**语义**：
- 服务启动时 `current_menu_id` 默认为 `"root"`，此时 `/intent/recognize` 的候选为 7 项一级业务（这是用户未发起任何界面跳转时语音模块的正常工作态）。
- `menu_id = "root"`：显式回到一级菜单，候选为 7 项一级业务。
- `menu_id = "new_card"` 或 `"replace_card"`：进入共享二级菜单，候选为 8 项"社会保障卡 xxx"。
- 其他一级叶子节点（`card_lost` / `card_unlost` / `info_query` / `change_pwd` / `reset_pwd`）的 `children` 为空，set 操作成功返回 200，但后续调用 `/intent/recognize` 时会返回 `no_candidates` 错误——正常情况下界面模块进入这些流程后不会再触发语音意图识别，此设计仅作为"状态机走错"的明确失败信号。

### 5.2 识别用户意图（语音/文字输入模块调用）

```
POST /intent/recognize
```

**Request**
```json
{ "text": "我要办一张新卡" }
```

**Response 200（命中）**
```json
{
  "matched": true,
  "intent_id": "new_card",
  "intent_name": "新制卡"
}
```

**Response 200（未命中）**
```json
{
  "matched": false,
  "intent_id": "unknown",
  "intent_name": "未识别"
}
```

**Response 400（当前菜单无候选）**
```json
{ "error": "no_candidates", "current_menu": "card_lost" }
```

**Response 422（请求体非法：缺 `text` 字段或类型错误）**
由 FastAPI / pydantic 自动返回，字段符合 pydantic 默认错误格式。

**空字符串或纯空白输入**：服务端在进入 recognizer 前做 `text.strip()`，若为空直接返回 `matched: false, intent_id: "unknown", intent_name: "未识别"`，不调用 Ollama。

**Response 503（Ollama 不可达或超时）**
```json
{ "error": "llm_unavailable" }
```

### 5.3 健康检查

```
GET /healthz
```
返回：
```json
{ "status": "ok", "ollama_reachable": true, "current_menu": "root" }
```
即便 Ollama 不可达也返回 HTTP 200，仅 `ollama_reachable: false`，便于运维区分"服务本身存活"和"下游挂了"。

**`ollama_reachable` 探测方式**：每次调用 `/healthz` 时对 `GET {OLLAMA_URL}/api/tags` 做一次实时探测，超时 2 秒。非 200 或超时均视为 `false`。不缓存——healthz 调用频率本就低（通常由 compose healthcheck 15s 一次），实时探测最可靠。

### 5.4 调用时序

```
界面模块                意图服务                语音模块
   |                     |                      |
   |-- POST /state/menu ->|                      |   # 用户刚进入新制卡二级界面
   |   {menu_id:"new_card"}                      |
   |<-- 200 -------------|                      |
   |                     |                      |
   |                     |<-- POST /intent/recognize --|  # 用户说话
   |                     |   {text:"办应用状态查询"}   |
   |                     |--- 200 -------------->|
   |                     |   {intent_id:"app_status_query", ...}
```

状态由界面模块驱动（它知道当前屏幕），识别由语音模块触发，两条线完全解耦。

## 6. 菜单 YAML 结构

扁平字典 + `parent` + `children` 构建树，每个节点带 `name / description / keywords` 用于 prompt 拼装。

```yaml
menus:
  root:
    name: "主菜单"
    parent: null
    description: "一级主菜单，用户选择要办理的业务类型"
    children: [new_card, replace_card, card_lost, card_unlost, info_query, change_pwd, reset_pwd]

  # 一级菜单（7 项，对应截图一）
  new_card:
    name: "新制卡"
    parent: root
    description: "首次申领社保卡，适用于从未办过卡的用户"
    keywords: ["新卡", "办卡", "申领", "第一次办", "没有卡", "新制卡"]
    children: [app_new_apply, app_replace, app_status_query, app_activate,
               app_change_pwd, app_reset_pwd, app_lost, app_unlost]

  replace_card:
    name: "补换卡"
    parent: root
    description: "卡片损坏、丢失后补办或换发新卡"
    keywords: ["补卡", "换卡", "旧卡坏了", "卡丢了要新的", "补办"]
    children: [app_new_apply, app_replace, app_status_query, app_activate,
               app_change_pwd, app_reset_pwd, app_lost, app_unlost]

  card_lost:
    name: "社保卡挂失"
    parent: root
    description: "卡片遗失后办理挂失，防止被盗用"
    keywords: ["挂失", "卡丢了", "丢失", "被偷了"]
    children: []

  card_unlost:
    name: "社保卡解挂"
    parent: root
    description: "已挂失的卡找回后解除挂失状态"
    keywords: ["解挂", "解除挂失", "卡找到了", "取消挂失"]
    children: []

  info_query:
    name: "社保信息查询"
    parent: root
    description: "查询社保缴费记录、账户余额等信息"
    keywords: ["查询", "查信息", "查余额", "查缴费", "看记录"]
    children: []

  change_pwd:
    name: "修改密码"
    parent: root
    description: "修改社保卡交易密码（需知道原密码）"
    keywords: ["改密码", "修改密码", "换密码"]
    children: []

  reset_pwd:
    name: "重置密码"
    parent: root
    description: "忘记原密码时重置社保卡交易密码"
    keywords: ["重置密码", "忘记密码", "密码忘了", "密码不记得"]
    children: []

  # 二级菜单（8 项，共享，对应截图二）
  # 注意：这些节点同时是 new_card 和 replace_card 的子节点，
  # 因此 parent 字段留空（null），语义上它们有多个父节点，
  # 不适合用单值字段表达。归属关系由父节点的 children 列表权威定义。
  app_new_apply:
    name: "社会保障卡新申领"
    parent: null
    description: "首次申请领取社会保障卡"
    keywords: ["新申领", "新办", "第一次领"]
    children: []

  app_replace:
    name: "社会保障卡补换卡"
    parent: null
    description: "补办或换发社会保障卡"
    keywords: ["补换卡", "补卡", "换卡"]
    children: []

  app_status_query:
    name: "社会保障卡应用状态查询"
    parent: null
    description: "查询社会保障卡的当前应用状态"
    keywords: ["应用状态", "状态查询", "卡状态"]
    children: []

  app_activate:
    name: "社会保障卡启用"
    parent: null
    description: "激活启用新领的社会保障卡"
    keywords: ["启用", "激活", "开卡"]
    children: []

  app_change_pwd:
    name: "社会保障卡交易密码修改"
    parent: null
    description: "修改社会保障卡的交易密码"
    keywords: ["交易密码修改", "改交易密码"]
    children: []

  app_reset_pwd:
    name: "社会保障卡交易密码重置"
    parent: null
    description: "重置社会保障卡的交易密码"
    keywords: ["交易密码重置", "忘记交易密码"]
    children: []

  app_lost:
    name: "社会保障卡挂失"
    parent: null
    description: "办理社会保障卡挂失"
    keywords: ["挂失", "卡丢了"]
    children: []

  app_unlost:
    name: "社会保障卡解挂"
    parent: null
    description: "解除社会保障卡的挂失状态"
    keywords: ["解挂", "解除挂失"]
    children: []
```

### 要点说明

1. **`new_card` 和 `replace_card` 挂相同的 children**：共享二级菜单的正确建模方式，无论用户从哪个入口进入，候选都是同一份 8 项。
2. **二级节点的 `parent` 字段统一为 `null`**：因为同一个节点同时属于两个父（`new_card` 和 `replace_card`），单值字段无法表达，用 `null` 明确"归属由父节点的 children 列表权威定义"。`parent` 字段只用于 `root` 的识别和可选的反向导航提示。
3. **ID 命名规则**：小写英文下划线；二级菜单加 `app_` 前缀以避免与一级菜单 ID 冲突并明示"社会保障卡应用 xxx"语义。
4. **`keywords` 可选字段**：作为语义提示注入 prompt，帮助 4b 小模型理解口语变体。不是规则匹配。
5. **`unknown` 不是菜单节点**：它是 recognizer 的保留返回值，不写在 YAML 里。

### 启动校验

启动时在 `menu.py` 里跑一遍：
- 所有 `children` 引用的 ID 必须存在。
- `root` 必须存在且 `parent == null`。
- 所有非 `root` 节点必须可从 `root` 经 `children` 链到达（可达性检查，防止孤岛）。
- ID 不能重复。
- 节点 `parent` 若非 `null`，允许任意值（文档性质，不做一致性校验）。

校验失败直接抛异常，服务启动失败。对应的失败场景在 `test_menu.py` 中必须有单测覆盖。

## 7. Recognizer 实现细节

### 7.1 Prompt 构造

System prompt（按当前候选动态拼装）：

```
你是重庆社保自助机的意图识别助手。
用户正在当前菜单界面说话，你需要从下面的候选业务项中选出用户最想办的那一项。

候选业务（只能从这里选）：
1. id=new_card  名称=新制卡  说明=首次申领社保卡，适用于从未办过卡的用户
   常见说法：新卡、办卡、申领、第一次办、没有卡、新制卡
2. id=replace_card  名称=补换卡  说明=卡片损坏、丢失后补办或换发新卡
   常见说法：补卡、换卡、旧卡坏了、卡丢了要新的、补办
...

规则：
- 只能选上面列出的 id 之一。
- 如果用户的话和所有候选都不相关，或含糊不清无法判断，返回 id="unknown"。
- 输出严格的 JSON，不要解释，不要多余文字。

输出格式：
{"intent_id": "<候选 id 或 unknown>"}
```

User prompt：
```
用户说：<原始文本>
```

**不使用 few-shot 示例**。

### 7.2 JSON Schema 动态构造

```python
schema = {
    "type": "object",
    "properties": {
        "intent_id": {
            "type": "string",
            "enum": [c.id for c in candidates] + ["unknown"]
        }
    },
    "required": ["intent_id"],
    "additionalProperties": False
}
```

### 7.3 Ollama 请求

```
POST {OLLAMA_URL}/api/chat
```

Body（所有字段从 `config` 注入，下面 JSON 只是示意实际形态）：
```json
{
  "model": "<config.MODEL_NAME>",
  "messages": [
    {"role": "system", "content": "<system prompt>"},
    {"role": "user",   "content": "用户说：<text>"}
  ],
  "format": <schema>,
  "stream": false,
  "options": {
    "temperature": <config.TEMPERATURE>,
    "num_predict": 64
  }
}
```

**`model` 字段必须从 `config.MODEL_NAME` 读取**，不得在代码中硬编码字符串字面量。`temperature` 同理，从 `config.TEMPERATURE` 读取。

### 7.4 响应解析与白名单兜底（含错误路径）

```python
def recognize(text: str, candidates: list[MenuNode]) -> IntentResult:
    # 空白输入短路，不调 Ollama
    if not text.strip():
        return IntentResult(matched=False, intent_id="unknown", intent_name="未识别")

    schema = build_schema(candidates)
    payload = build_payload(text, candidates, schema)

    try:
        resp = httpx.post(
            f"{config.OLLAMA_URL}/api/chat",
            json=payload,
            timeout=config.OLLAMA_TIMEOUT_SECONDS,  # 默认 30
        )
        resp.raise_for_status()
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as e:
        # 上抛至 api.py，由 handler 转成 HTTP 503 {"error": "llm_unavailable"}
        raise OllamaUnavailable(str(e)) from e

    content = resp.json().get("message", {}).get("content", "")

    try:
        intent_id = json.loads(content).get("intent_id", "unknown")
    except (json.JSONDecodeError, TypeError):
        intent_id = "unknown"

    valid_ids = {c.id for c in candidates} | {"unknown"}
    if intent_id not in valid_ids:
        intent_id = "unknown"

    if intent_id == "unknown":
        return IntentResult(matched=False, intent_id="unknown", intent_name="未识别")

    node = menu.get(intent_id)
    return IntentResult(matched=True, intent_id=intent_id, intent_name=node.name)
```

`OllamaUnavailable` 是本模块内定义的轻量异常，`api.py` 的 handler 用 `try/except OllamaUnavailable` 捕获并返回 `JSONResponse(status_code=503, content={"error": "llm_unavailable"})`。

### 7.5 错误处理映射

| 情况 | 处理 |
|---|---|
| Ollama 超时（httpx.TimeoutException） | 503 `{"error": "llm_unavailable"}` |
| Ollama 连接失败（httpx.ConnectError） | 503 同上 |
| Ollama 返回非 2xx（HTTPStatusError） | 503 同上 |
| 返回内容不是合法 JSON | 归为 `unknown`（200 响应） |
| 返回的 `intent_id` 不在白名单 | 归为 `unknown`（200 响应） |
| 请求体缺 `text` / 类型错误 | 422（FastAPI/pydantic 自动处理） |
| `text.strip() == ""` | 200 `unknown`（短路，不调 Ollama） |

### 7.6 请求耗时与日志

每次 `recognize` 调用完成后写一条结构化日志：

```
{
  "ts": "2026-04-14T12:34:56Z",
  "text": "我要办张新的社保卡",
  "candidates": ["new_card", "replace_card", ...],
  "intent_id": "new_card",
  "matched": true,
  "latency_ms": 842
}
```

日志走 Python `logging` 模块 stdout 输出，由 docker 捕获。为未来准确率统计和 prompt 调优保留数据。

### 7.7 并发

单用户场景。CPython GIL 保证 `state.current_menu_id` 单字段读写的原子性，`state.py` 无需显式加锁。若将来切换到多会话模型（见 §11），需要重新评估此处。

## 8. Docker 部署

由于 Ollama 由用户独立维护，本模块只容器化 `intent-service`。

### 8.1 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY config/ ./config/

ENV PYTHONUNBUFFERED=1 \
    OLLAMA_URL=http://host.docker.internal:11434 \
    MODEL_NAME=qwen3.5:4b \
    MENU_FILE=/app/config/menus.yaml \
    TEMPERATURE=0.2 \
    OLLAMA_TIMEOUT_SECONDS=30 \
    HEALTHZ_PROBE_TIMEOUT_SECONDS=2

EXPOSE 7666

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7666"]
```

### 8.2 requirements.txt

```
fastapi==0.115.*
uvicorn[standard]==0.30.*
httpx==0.27.*
pydantic==2.*
pyyaml==6.*
```

### 8.3 docker-compose.yml

```yaml
version: "3.9"

services:
  intent-service:
    build: .
    container_name: intent-service
    restart: unless-stopped
    environment:
      OLLAMA_URL: ${OLLAMA_URL:-http://host.docker.internal:11434}
      MODEL_NAME: ${MODEL_NAME:-qwen3.5:4b}
      MENU_FILE: /app/config/menus.yaml
      TEMPERATURE: "0.2"
    ports:
      - "7666:7666"
    extra_hosts:
      - "host.docker.internal:host-gateway"   # Linux 下让容器能访问宿主机
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:7666/healthz').raise_for_status()"]
      interval: 15s
      timeout: 5s
      retries: 3
```

### 8.4 部署说明

- Ollama 默认假设跑在宿主机上，容器通过 `host.docker.internal:11434` 访问。
- 若用户的 Ollama 跑在另一个独立容器/主机，启动时通过环境变量覆盖：
  ```bash
  OLLAMA_URL=http://10.0.0.5:11434 docker compose up -d
  ```
- 服务端口 **7666**，由外部调用方直接访问 `http://<host>:7666`。

### 8.5 启动流程

```bash
cd intent-service/
docker compose up -d --build
curl http://localhost:7666/healthz
```

## 9. 测试策略

- **`test_menu.py`**：
  - 加载合法 YAML，验证树结构、`get_candidates` 返回正确、`is_valid_id` 行为正确。
  - **启动校验失败用例**：缺 `root` 节点 / `children` 引用不存在的 ID / ID 重复 / 存在不可达节点——每种失败场景单独一个测试，断言抛出特定异常。
- **`test_recognizer.py`**：用 `httpx.MockTransport` 模拟 Ollama 响应，覆盖：
  - 正常命中（intent_id 在白名单内）
  - 模型返回 `"unknown"`
  - 模型返回非法 JSON（归为 unknown）
  - 模型返回白名单外的 ID（兜底归为 unknown）
  - `httpx.TimeoutException`（抛 `OllamaUnavailable`）
  - `httpx.ConnectError`（抛 `OllamaUnavailable`）
  - Ollama 返回 500（抛 `OllamaUnavailable`）
  - 空白输入（短路不调 Ollama，直接 unknown）
  - 不依赖真实 Ollama。
- **`test_api.py`**：FastAPI `TestClient`，覆盖：
  - `POST /state/menu` 合法 ID 200 / 非法 ID 404
  - `POST /intent/recognize` 正常命中 / unknown / 无候选 400 / Ollama 不可达 503 / 请求体非法 422
  - `GET /healthz` ollama 可达 / 不可达
  - 验证 `/state/menu` 的状态更新会影响后续 `/intent/recognize` 的候选集合。
- **手工端到端**：真实 Ollama + `qwen3.5:4b` 跑 10~20 条口语化测试语句（可沿用 `测试集.xlsx` 里的数据），确认识别质量达标。

## 10. 配置与环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama 服务地址 |
| `MODEL_NAME` | `qwen3.5:4b` | Ollama 模型 tag |
| `MENU_FILE` | `/app/config/menus.yaml` | 菜单树配置路径 |
| `TEMPERATURE` | `0.2` | LLM 采样温度 |
| `OLLAMA_TIMEOUT_SECONDS` | `30` | Ollama HTTP 调用超时 |
| `HEALTHZ_PROBE_TIMEOUT_SECONDS` | `2` | `/healthz` 探测 Ollama 时的超时 |

## 11. 未来可能的扩展（非当前工作范围）

- 识别失败时服务端自动追问（目前留给上层对话模块）。
- 多会话并发（切到按 `session_id` 存状态或用 Redis）。
- 菜单改版时从手册自动 diff 提取新增/删除节点，辅助人工维护 YAML。
- 日志持久化与识别准确率统计面板。

## 12. 设计中明确拒绝的选项

- **全局导航意图（NAV_BACK / NAV_HOME）**：用户确认由界面模块自行处理，不进入意图识别。
- **置信度输出与阈值拦截**：用户确认不做。
- **Few-shot 示例**：用户确认不加。
- **单容器 supervisord**：反模式。
- **Embedding 检索方案**：候选过少，不必要。
- **从 docx 手册自动解析菜单树**：手册章节结构与真实界面版本不完全对应，维护性差。
