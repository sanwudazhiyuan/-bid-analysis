# 社保自助机意图识别模块 · 实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个基于 Ollama qwen3.5:4b 的 HTTP 意图识别微服务，把用户的自然语言映射到重庆社保自助机菜单树上的业务项，通过两个 REST endpoint 与语音和界面模块交互，Docker 部署在端口 7666。

**Architecture:** FastAPI 薄壳 + pydantic 契约 + httpx 调 Ollama `/api/chat`（structured output JSON Schema 约束）+ 本地白名单兜底校验。单用户场景，状态用全局单例。菜单树从 YAML 加载，启动时做可达性和完整性校验。

**Tech Stack:** Python 3.11, FastAPI 0.115, uvicorn, httpx 0.27, pydantic 2, PyYAML, pytest, Docker。

**Spec reference:** [2026-04-14-intent-recognition-module-design.md](../specs/2026-04-14-intent-recognition-module-design.md)

**Project root (代码落位):** `d:/BaiduSyncdisk/数字人项目/intent-service/`

---

## 文件结构总览

实施前先固定文件责任边界（每个文件≤200 行，职责单一）：

| 文件 | 责任 | 依赖 |
|---|---|---|
| `app/config.py` | 读取并缓存所有环境变量 | os |
| `app/menu.py` | 加载 YAML、构建树、候选查询、启动校验 | yaml, config |
| `app/state.py` | 全局单例 `current_menu_id` | menu |
| `app/schemas.py` | pydantic 请求/响应模型 | pydantic |
| `app/recognizer.py` | 调 Ollama、schema 构造、白名单兜底、`OllamaUnavailable` 异常 | httpx, config, menu, schemas |
| `app/api.py` | 路由 handler，组装 state+menu+recognizer | fastapi, 其余 app.* |
| `app/main.py` | FastAPI app 入口，加载 menu、注册路由、启动校验 | fastapi, app.* |
| `config/menus.yaml` | 菜单树数据 | — |
| `tests/test_menu.py` | menu.py 的单测 | pytest |
| `tests/test_state.py` | state.py 的单测 | pytest |
| `tests/test_recognizer.py` | recognizer.py 的单测（httpx MockTransport） | pytest, httpx |
| `tests/test_api.py` | FastAPI TestClient 端到端（Ollama 仍被 mock） | pytest, fastapi.testclient |
| `Dockerfile` | intent-service 镜像 | — |
| `docker-compose.yml` | 单服务编排 | — |
| `requirements.txt` | 运行时依赖 | — |
| `requirements-dev.txt` | 测试/开发依赖 | — |
| `README.md` | 启动/部署/调用说明 | — |

---

## Chunk 1：项目骨架与配置

### Task 1：创建项目目录和依赖清单

**Files:**
- Create: `d:/BaiduSyncdisk/数字人项目/intent-service/requirements.txt`
- Create: `d:/BaiduSyncdisk/数字人项目/intent-service/requirements-dev.txt`
- Create: `d:/BaiduSyncdisk/数字人项目/intent-service/app/__init__.py`
- Create: `d:/BaiduSyncdisk/数字人项目/intent-service/tests/__init__.py`
- Create: `d:/BaiduSyncdisk/数字人项目/intent-service/config/.gitkeep`
- Create: `d:/BaiduSyncdisk/数字人项目/intent-service/.gitignore`

- [ ] **Step 1：创建目录结构**

```bash
cd "d:/BaiduSyncdisk/数字人项目"
mkdir -p intent-service/app intent-service/tests intent-service/config
```

- [ ] **Step 2：写入 `requirements.txt`**

```
fastapi==0.115.*
uvicorn[standard]==0.30.*
httpx==0.27.*
pydantic==2.*
pyyaml==6.*
```

- [ ] **Step 3：写入 `requirements-dev.txt`**

```
-r requirements.txt
pytest==8.*
```

- [ ] **Step 4：写入 `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
*.egg-info/
.env
```

- [ ] **Step 5：创建空 `app/__init__.py` 和 `tests/__init__.py`**

（空文件，让 Python 把它们识别为包）

- [ ] **Step 6：创建并激活 venv，安装依赖**

```bash
cd intent-service
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements-dev.txt
```

期望：全部安装成功，`pytest --version` 输出 8.x。

- [ ] **Step 7：Commit**

```bash
git add intent-service/
git commit -m "chore(intent-service): scaffold project skeleton"
```

---

### Task 2：配置模块 `config.py`

**Files:**
- Create: `intent-service/app/config.py`
- Create: `intent-service/tests/test_config.py`

- [ ] **Step 1：写失败测试 `tests/test_config.py`**

```python
import importlib
import os


def reload_config():
    import app.config as config
    importlib.reload(config)
    return config


def test_defaults(monkeypatch):
    for key in [
        "OLLAMA_URL", "MODEL_NAME", "MENU_FILE",
        "TEMPERATURE", "OLLAMA_TIMEOUT_SECONDS", "HEALTHZ_PROBE_TIMEOUT_SECONDS",
    ]:
        monkeypatch.delenv(key, raising=False)
    cfg = reload_config()
    assert cfg.OLLAMA_URL == "http://host.docker.internal:11434"
    assert cfg.MODEL_NAME == "qwen3.5:4b"
    assert cfg.MENU_FILE.endswith("menus.yaml")
    assert cfg.TEMPERATURE == 0.2
    assert cfg.OLLAMA_TIMEOUT_SECONDS == 30
    assert cfg.HEALTHZ_PROBE_TIMEOUT_SECONDS == 2


def test_overrides(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setenv("MODEL_NAME", "other-model")
    monkeypatch.setenv("TEMPERATURE", "0.5")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("HEALTHZ_PROBE_TIMEOUT_SECONDS", "1")
    cfg = reload_config()
    assert cfg.OLLAMA_URL == "http://localhost:11434"
    assert cfg.MODEL_NAME == "other-model"
    assert cfg.TEMPERATURE == 0.5
    assert cfg.OLLAMA_TIMEOUT_SECONDS == 15
    assert cfg.HEALTHZ_PROBE_TIMEOUT_SECONDS == 1
```

- [ ] **Step 2：跑测试确认失败**

```bash
cd intent-service && pytest tests/test_config.py -v
```

期望：`ModuleNotFoundError: No module named 'app.config'`。

- [ ] **Step 3：实现 `app/config.py`**

```python
import os

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3.5:4b")
MENU_FILE = os.getenv("MENU_FILE", os.path.join(os.path.dirname(__file__), "..", "config", "menus.yaml"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30"))
HEALTHZ_PROBE_TIMEOUT_SECONDS = int(os.getenv("HEALTHZ_PROBE_TIMEOUT_SECONDS", "2"))
```

- [ ] **Step 4：跑测试确认通过**

```bash
pytest tests/test_config.py -v
```

期望：2 passed。

- [ ] **Step 5：Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(intent-service): add config module reading env vars"
```

---

## Chunk 2：菜单树加载与校验

### Task 3：菜单加载器 `menu.py`

**Files:**
- Create: `intent-service/app/menu.py`
- Create: `intent-service/tests/test_menu.py`
- Create: `intent-service/tests/fixtures/valid_menus.yaml`
- Create: `intent-service/tests/fixtures/missing_root.yaml`
- Create: `intent-service/tests/fixtures/dangling_child.yaml`
- Create: `intent-service/tests/fixtures/unreachable_node.yaml`
- Create: `intent-service/tests/fixtures/duplicate_id.yaml`（真正的重复 mapping key）

- [ ] **Step 1：创建 fixture `valid_menus.yaml`**

（把 spec §6 的完整 YAML 内容放进去，作为合法样本。）

- [ ] **Step 2：创建 fixture `missing_root.yaml`**

```yaml
menus:
  new_card:
    name: "新制卡"
    parent: null
    children: []
```

- [ ] **Step 3：创建 fixture `dangling_child.yaml`**

```yaml
menus:
  root:
    name: "主菜单"
    parent: null
    children: [nonexistent_node]
```

- [ ] **Step 4：创建 fixture `unreachable_node.yaml`**

```yaml
menus:
  root:
    name: "主菜单"
    parent: null
    children: []
  orphan:
    name: "孤岛"
    parent: null
    children: []
```

- [ ] **Step 5：创建 fixture `duplicate_id.yaml`**

PyYAML 的 `safe_load` 会把重复 mapping key 默默去重。为了让 spec §6 "ID 不能重复" 的启动校验真正被覆盖，加载器用 **`yaml.compose`** 在 AST 层检测同一层 mapping 下的重复 key，然后才转成 dict。fixture 内容（文件里确实出现两次 `new_card` 键）：

```yaml
menus:
  root:
    name: "主菜单"
    parent: null
    children: [new_card]
  new_card:
    name: "新制卡 A"
    parent: root
    children: []
  new_card:
    name: "新制卡 B"
    parent: root
    children: []
```

这个 YAML 是"合法但有重复 key"，`yaml.compose` 会看到同一个 mapping 下出现两个 `ScalarNode` 值 `new_card`，触发校验失败。

- [ ] **Step 6：写失败测试 `tests/test_menu.py`**

```python
import pytest
from pathlib import Path

import app.menu as menu_mod

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_valid_menus():
    tree = menu_mod.load(FIXTURES / "valid_menus.yaml")
    assert tree.get("root").name == "主菜单"
    assert tree.get("new_card").name == "新制卡"
    assert "app_status_query" in [c.id for c in tree.get_candidates("new_card")]
    assert len(tree.get_candidates("new_card")) == 8
    assert len(tree.get_candidates("replace_card")) == 8
    assert tree.get_candidates("card_lost") == []
    assert tree.get_candidates("root")[0].id == "new_card"
    assert len(tree.get_candidates("root")) == 7


def test_is_valid_id():
    tree = menu_mod.load(FIXTURES / "valid_menus.yaml")
    assert tree.is_valid_id("new_card")
    assert tree.is_valid_id("app_lost")
    assert not tree.is_valid_id("nonexistent")


def test_missing_root_raises():
    with pytest.raises(menu_mod.MenuValidationError, match="root"):
        menu_mod.load(FIXTURES / "missing_root.yaml")


def test_dangling_child_raises():
    with pytest.raises(menu_mod.MenuValidationError, match="nonexistent_node"):
        menu_mod.load(FIXTURES / "dangling_child.yaml")


def test_unreachable_node_raises():
    with pytest.raises(menu_mod.MenuValidationError, match="unreachable|orphan"):
        menu_mod.load(FIXTURES / "unreachable_node.yaml")


def test_duplicate_id_raises():
    with pytest.raises(menu_mod.MenuValidationError, match="duplicate"):
        menu_mod.load(FIXTURES / "duplicate_id.yaml")
```

- [ ] **Step 7：跑测试确认失败**

```bash
pytest tests/test_menu.py -v
```

期望：全部失败，`ModuleNotFoundError` 或 `AttributeError`。

- [ ] **Step 8：实现 `app/menu.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml


class MenuValidationError(ValueError):
    """菜单 YAML 校验失败"""


@dataclass
class MenuNode:
    id: str
    name: str
    parent: str | None
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)


class MenuTree:
    def __init__(self, nodes: dict[str, MenuNode]):
        self._nodes = nodes

    def get(self, node_id: str) -> MenuNode:
        return self._nodes[node_id]

    def is_valid_id(self, node_id: str) -> bool:
        return node_id in self._nodes

    def get_candidates(self, node_id: str) -> list[MenuNode]:
        node = self._nodes.get(node_id)
        if node is None:
            return []
        return [self._nodes[cid] for cid in node.children]

    def all_ids(self) -> Iterable[str]:
        return self._nodes.keys()


def _detect_duplicate_keys(yaml_text: str) -> None:
    """在 AST 层检测同级 mapping 下重复的 key。

    PyYAML 的 safe_load 会默默去重；这里用 compose 拿到 MappingNode，
    遍历所有嵌套 mapping 的 key 列表，发现重复就抛错。
    """
    node = yaml.compose(yaml_text)
    if node is None:
        return

    def walk(n):
        from yaml import MappingNode, SequenceNode
        if isinstance(n, MappingNode):
            seen: set[str] = set()
            for key_node, value_node in n.value:
                k = key_node.value
                if k in seen:
                    raise MenuValidationError(f"duplicate key in yaml: {k!r}")
                seen.add(k)
                walk(value_node)
        elif isinstance(n, SequenceNode):
            for child in n.value:
                walk(child)

    walk(node)


def _check_root(nodes: dict[str, MenuNode]) -> None:
    if "root" not in nodes:
        raise MenuValidationError("missing root node")
    if nodes["root"].parent is not None:
        raise MenuValidationError("root node must have parent=null")


def _check_dangling_children(nodes: dict[str, MenuNode]) -> None:
    for node in nodes.values():
        for child_id in node.children:
            if child_id not in nodes:
                raise MenuValidationError(
                    f"node {node.id!r} references non-existent child {child_id!r}"
                )


def _check_reachable(nodes: dict[str, MenuNode]) -> None:
    reachable: set[str] = set()
    stack = ["root"]
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        stack.extend(nodes[cur].children)
    unreachable = set(nodes.keys()) - reachable
    if unreachable:
        raise MenuValidationError(
            f"unreachable nodes from root: {sorted(unreachable)}"
        )


def load(yaml_path: str | Path) -> MenuTree:
    path = Path(yaml_path)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    _detect_duplicate_keys(text)
    raw = yaml.safe_load(text)

    if not raw or "menus" not in raw:
        raise MenuValidationError("yaml missing top-level 'menus' key")

    menus_raw = raw["menus"]
    if not isinstance(menus_raw, dict):
        raise MenuValidationError("'menus' must be a mapping")

    nodes: dict[str, MenuNode] = {}
    for node_id, body in menus_raw.items():
        nodes[node_id] = MenuNode(
            id=node_id,
            name=body.get("name", node_id),
            parent=body.get("parent"),
            description=body.get("description", ""),
            keywords=list(body.get("keywords") or []),
            children=list(body.get("children") or []),
        )

    _check_root(nodes)
    _check_dangling_children(nodes)
    _check_reachable(nodes)

    return MenuTree(nodes)
```

- [ ] **Step 9：跑测试确认通过**

```bash
pytest tests/test_menu.py -v
```

期望：6 passed。

- [ ] **Step 10：Commit**

```bash
git add app/menu.py tests/test_menu.py tests/fixtures/
git commit -m "feat(intent-service): add menu loader with startup validation"
```

---

### Task 4：配置真实的 `config/menus.yaml`

**Files:**
- Create: `intent-service/config/menus.yaml`

- [ ] **Step 1：把 spec §6 的完整 YAML 内容拷贝到 `config/menus.yaml`**

（注意：二级节点 `parent: null`，`new_card` 和 `replace_card` 的 children 列表完全相同。）

- [ ] **Step 2：加一个 smoke 测试验证真实文件能被加载**

在 `tests/test_menu.py` 追加：

```python
def test_real_menus_yaml_loads():
    real_path = Path(__file__).parent.parent / "config" / "menus.yaml"
    tree = menu_mod.load(real_path)
    assert len(list(tree.all_ids())) == 16  # 1 root + 7 level-1 + 8 level-2
    assert set(c.id for c in tree.get_candidates("new_card")) == set(
        c.id for c in tree.get_candidates("replace_card")
    )
```

- [ ] **Step 3：跑测试**

```bash
pytest tests/test_menu.py::test_real_menus_yaml_loads -v
```

期望：PASS。如果失败，说明 YAML 抄写有误——修正 YAML。

- [ ] **Step 4：Commit**

```bash
git add config/menus.yaml tests/test_menu.py
git commit -m "feat(intent-service): add real menu tree config"
```

---

## Chunk 3：状态单例与 pydantic schemas

### Task 5：状态单例 `state.py`

**Files:**
- Create: `intent-service/app/state.py`
- Create: `intent-service/tests/test_state.py`

- [ ] **Step 1：写失败测试 `tests/test_state.py`**

```python
import app.state as state_mod


def test_default_is_root():
    s = state_mod.State()
    assert s.get() == "root"


def test_set_and_get():
    s = state_mod.State()
    s.set("new_card")
    assert s.get() == "new_card"


def test_module_level_singleton():
    state_mod.state.set("replace_card")
    assert state_mod.state.get() == "replace_card"
    state_mod.state.set("root")  # reset for other tests
```

- [ ] **Step 2：跑测试确认失败**

```bash
pytest tests/test_state.py -v
```

- [ ] **Step 3：实现 `app/state.py`**

```python
class State:
    def __init__(self) -> None:
        self._menu_id: str = "root"

    def get(self) -> str:
        return self._menu_id

    def set(self, menu_id: str) -> None:
        self._menu_id = menu_id


state = State()
```

- [ ] **Step 4：跑测试确认通过**

```bash
pytest tests/test_state.py -v
```

- [ ] **Step 5：Commit**

```bash
git add app/state.py tests/test_state.py
git commit -m "feat(intent-service): add global singleton menu state"
```

---

### Task 6：Pydantic schemas

**Files:**
- Create: `intent-service/app/schemas.py`
- Create: `intent-service/tests/test_schemas.py`

- [ ] **Step 1：写失败测试**

```python
import pytest
from pydantic import ValidationError

from app.schemas import (
    SetMenuRequest, SetMenuResponse,
    RecognizeRequest, RecognizeResponse,
    ErrorResponse, IntentResult,
)


def test_set_menu_request_valid():
    req = SetMenuRequest(menu_id="new_card")
    assert req.menu_id == "new_card"


def test_set_menu_request_missing_field():
    with pytest.raises(ValidationError):
        SetMenuRequest()


def test_recognize_request_requires_text():
    with pytest.raises(ValidationError):
        RecognizeRequest()


def test_recognize_response_matched():
    r = RecognizeResponse(matched=True, intent_id="new_card", intent_name="新制卡")
    assert r.matched is True


def test_recognize_response_unknown():
    r = RecognizeResponse(matched=False, intent_id="unknown", intent_name="未识别")
    assert r.matched is False
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：实现 `app/schemas.py`**

```python
from dataclasses import dataclass
from pydantic import BaseModel, Field


class SetMenuRequest(BaseModel):
    menu_id: str = Field(..., min_length=1)


class SetMenuResponse(BaseModel):
    menu_id: str
    menu_name: str


class RecognizeRequest(BaseModel):
    text: str = Field(...)


class RecognizeResponse(BaseModel):
    matched: bool
    intent_id: str
    intent_name: str


class ErrorResponse(BaseModel):
    error: str
    menu_id: str | None = None
    current_menu: str | None = None


@dataclass
class IntentResult:
    matched: bool
    intent_id: str
    intent_name: str
```

- [ ] **Step 4：跑测试确认通过**

- [ ] **Step 5：Commit**

```bash
git add app/schemas.py tests/test_schemas.py
git commit -m "feat(intent-service): add pydantic request/response schemas"
```

---

## Chunk 4：Recognizer（意图识别核心）

### Task 7：Schema 构造与 Prompt 拼装（纯函数部分）

**Files:**
- Create: `intent-service/app/recognizer.py`（先只填 schema 构造 + prompt 构造 + 异常类）
- Create: `intent-service/tests/test_recognizer.py`（先只测纯函数）

- [ ] **Step 1：写失败测试（schema 构造）**

```python
import pytest

from app.menu import MenuNode
from app.recognizer import build_schema, build_system_prompt, OllamaUnavailable


def _cand(ids):
    return [MenuNode(id=i, name=i, parent=None, description="", keywords=[], children=[]) for i in ids]


def test_schema_enum_includes_candidates_and_unknown():
    schema = build_schema(_cand(["a", "b"]))
    assert schema["type"] == "object"
    enum_vals = schema["properties"]["intent_id"]["enum"]
    assert set(enum_vals) == {"a", "b", "unknown"}
    assert schema["required"] == ["intent_id"]
    assert schema["additionalProperties"] is False


def test_system_prompt_lists_candidates():
    nodes = [
        MenuNode(id="new_card", name="新制卡", parent=None,
                 description="首次申领社保卡", keywords=["新卡", "办卡"], children=[]),
        MenuNode(id="replace_card", name="补换卡", parent=None,
                 description="补办换发", keywords=["补卡"], children=[]),
    ]
    prompt = build_system_prompt(nodes)
    assert "new_card" in prompt
    assert "新制卡" in prompt
    assert "首次申领社保卡" in prompt
    assert "新卡" in prompt
    assert "unknown" in prompt
    assert "JSON" in prompt
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：实现 `app/recognizer.py` 中的纯函数**

```python
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app import config
from app.menu import MenuNode, MenuTree
from app.schemas import IntentResult

logger = logging.getLogger("intent_recognizer")


class OllamaUnavailable(RuntimeError):
    """Ollama 不可达或返回错误"""


def build_schema(candidates: list[MenuNode]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "intent_id": {
                "type": "string",
                "enum": [c.id for c in candidates] + ["unknown"],
            }
        },
        "required": ["intent_id"],
        "additionalProperties": False,
    }


def build_system_prompt(candidates: list[MenuNode]) -> str:
    lines = [
        "你是重庆社保自助机的意图识别助手。",
        "用户正在当前菜单界面说话，你需要从下面的候选业务项中选出用户最想办的那一项。",
        "",
        "候选业务（只能从这里选）：",
    ]
    for i, node in enumerate(candidates, 1):
        desc = node.description or ""
        kw = "、".join(node.keywords) if node.keywords else ""
        lines.append(f"{i}. id={node.id}  名称={node.name}  说明={desc}")
        if kw:
            lines.append(f"   常见说法：{kw}")
    lines += [
        "",
        "规则：",
        "- 只能选上面列出的 id 之一。",
        '- 如果用户的话和所有候选都不相关，或含糊不清无法判断，返回 id="unknown"。',
        "- 输出严格的 JSON，不要解释，不要多余文字。",
        "",
        "输出格式：",
        '{"intent_id": "<候选 id 或 unknown>"}',
    ]
    return "\n".join(lines)


def build_payload(text: str, candidates: list[MenuNode], schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": config.MODEL_NAME,
        "messages": [
            {"role": "system", "content": build_system_prompt(candidates)},
            {"role": "user", "content": f"用户说：{text}"},
        ],
        "format": schema,
        "stream": False,
        "options": {
            "temperature": config.TEMPERATURE,
            "num_predict": 64,
        },
    }
```

- [ ] **Step 4：跑测试确认通过**

- [ ] **Step 5：Commit**

```bash
git add app/recognizer.py tests/test_recognizer.py
git commit -m "feat(intent-service): add recognizer schema and prompt builders"
```

---

### Task 8：`recognize()` 函数（核心 + httpx mock）

**Files:**
- Modify: `intent-service/app/recognizer.py`
- Modify: `intent-service/tests/test_recognizer.py`

- [ ] **Step 1：追加失败测试（`recognize()` 的 8 条路径）**

```python
import json
import httpx

from app.menu import MenuNode
from app.recognizer import recognize, OllamaUnavailable


def _cand(ids):
    return [MenuNode(id=i, name=f"name_{i}", parent=None, description="", keywords=[], children=[]) for i in ids]


def _make_client(response_factory):
    transport = httpx.MockTransport(response_factory)
    return httpx.Client(transport=transport)


def test_recognize_happy_path():
    def handler(request):
        assert request.url.path == "/api/chat"
        return httpx.Response(200, json={"message": {"content": json.dumps({"intent_id": "new_card"})}})

    client = _make_client(handler)
    result = recognize("我要办新卡", _cand(["new_card", "replace_card"]), client=client)
    assert result.matched is True
    assert result.intent_id == "new_card"
    assert result.intent_name == "name_new_card"


def test_recognize_unknown_from_model():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": json.dumps({"intent_id": "unknown"})}})

    result = recognize("今天天气不错", _cand(["new_card"]), client=_make_client(handler))
    assert result.matched is False
    assert result.intent_id == "unknown"
    assert result.intent_name == "未识别"


def test_recognize_invalid_json_content():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "not a json"}})

    result = recognize("含糊", _cand(["new_card"]), client=_make_client(handler))
    assert result.matched is False
    assert result.intent_id == "unknown"


def test_recognize_whitelist_fallback():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": json.dumps({"intent_id": "hallucinated_id"})}})

    result = recognize("随便", _cand(["new_card"]), client=_make_client(handler))
    assert result.matched is False
    assert result.intent_id == "unknown"


def test_recognize_timeout_raises():
    def handler(request):
        raise httpx.TimeoutException("timeout")

    with pytest.raises(OllamaUnavailable):
        recognize("慢", _cand(["new_card"]), client=_make_client(handler))


def test_recognize_connect_error_raises():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(OllamaUnavailable):
        recognize("挂了", _cand(["new_card"]), client=_make_client(handler))


def test_recognize_5xx_raises():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(OllamaUnavailable):
        recognize("错", _cand(["new_card"]), client=_make_client(handler))


def test_recognize_empty_text_shortcircuit():
    # 没有 handler，调用不能到达 httpx
    def handler(request):
        raise AssertionError("should not call ollama for empty text")

    result = recognize("   ", _cand(["new_card"]), client=_make_client(handler))
    assert result.matched is False
    assert result.intent_id == "unknown"
```

- [ ] **Step 2：跑测试确认失败**

```bash
pytest tests/test_recognizer.py -v
```

- [ ] **Step 3：实现 `recognize()`**

追加到 `app/recognizer.py` 末尾：

```python
def recognize(
    text: str,
    candidates: list[MenuNode],
    client: httpx.Client | None = None,
) -> IntentResult:
    if not text.strip():
        return IntentResult(matched=False, intent_id="unknown", intent_name="未识别")

    schema = build_schema(candidates)
    payload = build_payload(text, candidates, schema)
    start = time.monotonic()

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=config.OLLAMA_TIMEOUT_SECONDS)

    try:
        try:
            resp = client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
            resp.raise_for_status()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as e:
            raise OllamaUnavailable(str(e)) from e

        content = resp.json().get("message", {}).get("content", "")
    finally:
        if owns_client:
            client.close()

    try:
        intent_id = json.loads(content).get("intent_id", "unknown")
    except (json.JSONDecodeError, TypeError):
        intent_id = "unknown"

    valid_ids = {c.id for c in candidates} | {"unknown"}
    if intent_id not in valid_ids:
        intent_id = "unknown"

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        json.dumps(
            {
                "event": "recognize",
                "text": text,
                "candidates": [c.id for c in candidates],
                "intent_id": intent_id,
                "matched": intent_id != "unknown",
                "latency_ms": latency_ms,
            },
            ensure_ascii=False,
        )
    )

    if intent_id == "unknown":
        return IntentResult(matched=False, intent_id="unknown", intent_name="未识别")

    # 找候选里对应的 name
    name = next((c.name for c in candidates if c.id == intent_id), intent_id)
    return IntentResult(matched=True, intent_id=intent_id, intent_name=name)
```

注意：`recognize()` 通过 `client` 参数支持依赖注入，单测里可以注入 `MockTransport` 的 client。

- [ ] **Step 4：跑测试确认通过**

```bash
pytest tests/test_recognizer.py -v
```

期望：10 passed（2 纯函数 + 8 recognize 路径）。

- [ ] **Step 5：Commit**

```bash
git add app/recognizer.py tests/test_recognizer.py
git commit -m "feat(intent-service): implement recognize() with httpx and whitelist fallback"
```

---

## Chunk 5：FastAPI 路由与 HTTP 契约

### Task 9：FastAPI main 入口与 `/healthz`

**Files:**
- Create: `intent-service/app/main.py`
- Create: `intent-service/app/api.py`
- Create: `intent-service/tests/test_api.py`

- [ ] **Step 1：写失败测试 `tests/test_api.py`（先只测 `/healthz` 路径）**

```python
import json
import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    # 指向真实 config/menus.yaml（已在 Task 4 创建）
    from pathlib import Path
    repo_menus = Path(__file__).parent.parent / "config" / "menus.yaml"
    monkeypatch.setenv("MENU_FILE", str(repo_menus))

    # 按依赖顺序 reload，确保 api / main 使用最新 config 和重新加载的菜单树
    import importlib
    import app.config
    import app.menu
    import app.state
    import app.recognizer
    import app.api
    import app.main
    for mod in (app.config, app.menu, app.state, app.recognizer, app.api, app.main):
        importlib.reload(mod)
    # 把 state 显式重置到 root，避免测试之间泄漏
    app.state.state.set("root")
    return TestClient(app.main.app)


def test_healthz_ok_when_ollama_reachable(client, monkeypatch):
    def fake_tags(url, timeout):
        class R:
            status_code = 200
            def raise_for_status(self): pass
        return R()
    monkeypatch.setattr("app.api._probe_ollama", lambda: True)
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ollama_reachable"] is True
    assert body["current_menu"] == "root"


def test_healthz_ok_when_ollama_unreachable(client, monkeypatch):
    monkeypatch.setattr("app.api._probe_ollama", lambda: False)
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ollama_reachable"] is False
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：实现 `app/api.py`（先只填 `/healthz`）**

```python
from fastapi import APIRouter
import httpx

from app import config
from app.state import state
from app.menu import MenuTree

router = APIRouter()

# 由 main.py 在启动时注入
_menu_tree: MenuTree | None = None


def set_menu_tree(tree: MenuTree) -> None:
    global _menu_tree
    _menu_tree = tree


def _probe_ollama() -> bool:
    try:
        with httpx.Client(timeout=config.HEALTHZ_PROBE_TIMEOUT_SECONDS) as client:
            r = client.get(f"{config.OLLAMA_URL}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


@router.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "ollama_reachable": _probe_ollama(),
        "current_menu": state.get(),
    }
```

- [ ] **Step 4：实现 `app/main.py`**

```python
import logging

from fastapi import FastAPI

from app import api, config, menu


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    tree = menu.load(config.MENU_FILE)
    api.set_menu_tree(tree)

    app = FastAPI(title="Intent Recognition Service", version="1.0")
    app.include_router(api.router)
    return app


app = create_app()
```

- [ ] **Step 5：跑测试确认通过**

```bash
pytest tests/test_api.py -v
```

- [ ] **Step 6：Commit**

```bash
git add app/api.py app/main.py tests/test_api.py
git commit -m "feat(intent-service): add FastAPI app skeleton and /healthz"
```

---

### Task 10：`POST /state/menu`

**Files:**
- Modify: `intent-service/app/api.py`
- Modify: `intent-service/tests/test_api.py`

- [ ] **Step 1：追加失败测试**

```python
def test_set_menu_root(client):
    r = client.post("/state/menu", json={"menu_id": "root"})
    assert r.status_code == 200
    assert r.json() == {"menu_id": "root", "menu_name": "主菜单"}


def test_set_menu_new_card(client):
    r = client.post("/state/menu", json={"menu_id": "new_card"})
    assert r.status_code == 200
    assert r.json()["menu_name"] == "新制卡"


def test_set_menu_unknown_id(client):
    r = client.post("/state/menu", json={"menu_id": "foo_bar"})
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_menu_id"
    assert r.json()["menu_id"] == "foo_bar"


def test_set_menu_missing_field(client):
    r = client.post("/state/menu", json={})
    assert r.status_code == 422
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：在 `api.py` 追加路由**

```python
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.schemas import SetMenuRequest


@router.post("/state/menu")
def set_menu(req: SetMenuRequest):
    assert _menu_tree is not None
    if not _menu_tree.is_valid_id(req.menu_id):
        return JSONResponse(
            status_code=404,
            content={"error": "unknown_menu_id", "menu_id": req.menu_id},
        )
    node = _menu_tree.get(req.menu_id)
    state.set(req.menu_id)
    return {"menu_id": node.id, "menu_name": node.name}
```

- [ ] **Step 4：跑测试确认通过**

- [ ] **Step 5：Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "feat(intent-service): implement POST /state/menu endpoint"
```

---

### Task 11：`POST /intent/recognize`

**Files:**
- Modify: `intent-service/app/api.py`
- Modify: `intent-service/tests/test_api.py`

- [ ] **Step 1：追加失败测试（mock recognizer）**

```python
def test_recognize_happy(client, monkeypatch):
    from app.schemas import IntentResult
    monkeypatch.setattr(
        "app.api.recognizer.recognize",
        lambda text, candidates: IntentResult(matched=True, intent_id="new_card", intent_name="新制卡"),
    )
    client.post("/state/menu", json={"menu_id": "root"})
    r = client.post("/intent/recognize", json={"text": "我要办卡"})
    assert r.status_code == 200
    assert r.json() == {"matched": True, "intent_id": "new_card", "intent_name": "新制卡"}


def test_recognize_unknown(client, monkeypatch):
    from app.schemas import IntentResult
    monkeypatch.setattr(
        "app.api.recognizer.recognize",
        lambda text, candidates: IntentResult(matched=False, intent_id="unknown", intent_name="未识别"),
    )
    r = client.post("/intent/recognize", json={"text": "今天天气好"})
    assert r.status_code == 200
    assert r.json()["matched"] is False


def test_recognize_no_candidates(client):
    client.post("/state/menu", json={"menu_id": "card_lost"})
    r = client.post("/intent/recognize", json={"text": "随便说"})
    assert r.status_code == 400
    assert r.json()["error"] == "no_candidates"
    assert r.json()["current_menu"] == "card_lost"


def test_recognize_llm_unavailable(client, monkeypatch):
    from app.recognizer import OllamaUnavailable
    def boom(*args, **kwargs):
        raise OllamaUnavailable("timeout")
    monkeypatch.setattr("app.api.recognizer.recognize", boom)
    client.post("/state/menu", json={"menu_id": "root"})
    r = client.post("/intent/recognize", json={"text": "办卡"})
    assert r.status_code == 503
    assert r.json()["error"] == "llm_unavailable"


def test_recognize_missing_text(client):
    r = client.post("/intent/recognize", json={})
    assert r.status_code == 422


def test_recognize_state_drives_candidates(client, monkeypatch):
    """确认 state 变化会改变送入 recognizer 的 candidates"""
    captured = {}
    from app.schemas import IntentResult
    def fake(text, candidates):
        captured["ids"] = [c.id for c in candidates]
        return IntentResult(matched=True, intent_id=candidates[0].id, intent_name=candidates[0].name)
    monkeypatch.setattr("app.api.recognizer.recognize", fake)

    client.post("/state/menu", json={"menu_id": "root"})
    client.post("/intent/recognize", json={"text": "随便"})
    assert "new_card" in captured["ids"]
    assert len(captured["ids"]) == 7

    client.post("/state/menu", json={"menu_id": "new_card"})
    client.post("/intent/recognize", json={"text": "随便"})
    assert "app_status_query" in captured["ids"]
    assert len(captured["ids"]) == 8
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：在 `api.py` 追加路由**

```python
from app import recognizer
from app.schemas import RecognizeRequest
from app.recognizer import OllamaUnavailable


@router.post("/intent/recognize")
def recognize_intent(req: RecognizeRequest):
    assert _menu_tree is not None
    current = state.get()
    candidates = _menu_tree.get_candidates(current)
    if not candidates:
        return JSONResponse(
            status_code=400,
            content={"error": "no_candidates", "current_menu": current},
        )

    try:
        result = recognizer.recognize(req.text, candidates)
    except OllamaUnavailable:
        return JSONResponse(
            status_code=503,
            content={"error": "llm_unavailable"},
        )

    return {
        "matched": result.matched,
        "intent_id": result.intent_id,
        "intent_name": result.intent_name,
    }
```

- [ ] **Step 4：跑测试确认通过**

```bash
pytest tests/test_api.py -v
```

期望：所有 test_api.py 测试通过（健康检查 2 条 + set_menu 4 条 + recognize 6 条 = 12 条）。

- [ ] **Step 5：跑整套测试确保没有回归**

```bash
pytest -v
```

期望：全 PASS。

- [ ] **Step 6：Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "feat(intent-service): implement POST /intent/recognize endpoint"
```

---

## Chunk 6：本地运行 + Docker 部署

### Task 12：本地 uvicorn 启动并手工验证

**Files:**
- Create: `intent-service/README.md`

- [ ] **Step 1：写 README**

最小内容：如何本地启、如何 Docker 启、两个 endpoint 的 curl 示例（可从 spec §5 搬运）、环境变量表（从 spec §10 搬运）、开发环境依赖安装。

- [ ] **Step 2：本地启服务**

```bash
cd intent-service
source .venv/Scripts/activate
uvicorn app.main:app --host 0.0.0.0 --port 7666 --reload
```

期望：启动成功，日志显示 "Uvicorn running on http://0.0.0.0:7666"。

- [ ] **Step 3：手工验证 `/healthz`**

另开一个终端：

```bash
curl http://localhost:7666/healthz
```

期望 JSON：`{"status":"ok","ollama_reachable":true或false,"current_menu":"root"}`。如果 Ollama 跑在宿主机 11434，应该 `ollama_reachable: true`。

- [ ] **Step 4：手工验证 `/state/menu` + `/intent/recognize`**

```bash
curl -X POST http://localhost:7666/state/menu -H "Content-Type: application/json" -d '{"menu_id": "root"}'
curl -X POST http://localhost:7666/intent/recognize -H "Content-Type: application/json" -d '{"text": "我想办张新卡"}'
```

期望第二条返回 `{"matched": true, "intent_id": "new_card", "intent_name": "新制卡"}`（需 Ollama 可用）。

- [ ] **Step 5：停服务并 commit**

```bash
git add README.md
git commit -m "docs(intent-service): add README with run/curl instructions"
```

---

### Task 13：Dockerfile

**Files:**
- Create: `intent-service/Dockerfile`

- [ ] **Step 1：写 `Dockerfile`**

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

- [ ] **Step 2：构建镜像**

```bash
cd intent-service
docker build -t intent-service:dev .
```

期望：构建成功，无 error。镜像 < 200 MB。

- [ ] **Step 3：Commit**

```bash
git add Dockerfile
git commit -m "build(intent-service): add Dockerfile"
```

---

### Task 14：docker-compose.yml 与整体 smoke 测试

**Files:**
- Create: `intent-service/docker-compose.yml`

- [ ] **Step 1：写 `docker-compose.yml`**

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
      - "host.docker.internal:host-gateway"
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:7666/healthz').raise_for_status()"]
      interval: 15s
      timeout: 5s
      retries: 3
```

- [ ] **Step 2：启动容器**

```bash
cd intent-service
docker compose up -d --build
docker compose ps
```

期望：`intent-service` 状态为 `running`，健康检查过一会后变为 `healthy`。

- [ ] **Step 3：端到端验证**

```bash
curl http://localhost:7666/healthz
curl -X POST http://localhost:7666/state/menu -H "Content-Type: application/json" -d '{"menu_id": "new_card"}'
curl -X POST http://localhost:7666/intent/recognize -H "Content-Type: application/json" -d '{"text": "我要查社保卡应用状态"}'
```

期望：
- `/healthz` 返回 `ollama_reachable: true`（如果宿主机 Ollama 可达）
- 第三条返回 `{"matched": true, "intent_id": "app_status_query", ...}`

- [ ] **Step 4：挑 5~10 条口语化测试语句跑人肉准确率**

可从 `d:/BaiduSyncdisk/数字人项目/测试集.xlsx` 拿数据。记录哪些命中、哪些 miss，若准确率 < 80% 回头调 prompt 或 keywords。

- [ ] **Step 5：清理容器**

```bash
docker compose down
```

- [ ] **Step 6：Commit**

```bash
git add docker-compose.yml
git commit -m "build(intent-service): add docker-compose for single-service deployment"
```

---

## 验收清单

实施完成后确认全部满足：

- [ ] `pytest -v` 全绿（config, menu, state, schemas, recognizer, api 共 30+ 条测试）
- [ ] `docker compose up -d` 启动成功，`docker compose ps` 显示 healthy
- [ ] `curl /healthz` 返回正确结构
- [ ] `curl /state/menu` 合法 ID 返回 200；非法 ID 返回 404
- [ ] `curl /intent/recognize` 配合真实 Ollama 能识别 "新制卡" "补换卡" "应用状态查询" 等典型语句
- [ ] 当前菜单为叶子节点时 recognize 返回 400 `no_candidates`
- [ ] 停掉 Ollama 后 recognize 返回 503 `llm_unavailable`
- [ ] 口语化测试集 ≥10 条，准确率 ≥ 80%（人工判定）
- [ ] Spec 中"设计中拒绝的选项"没有任何一条被偷偷引入（无全局导航 intent、无置信度、无 few-shot）

---

## 说明

- **TDD 遵守**：每个 Task 严格按 写测试 → 跑失败 → 实现 → 跑通过 → commit 的节奏。
- **小步提交**：每完成一个 Task commit 一次，保持 diff 可回滚。
- **依赖注入测试**：`recognizer.recognize` 可选 `client` 参数，让单测能用 `httpx.MockTransport` 避免依赖真实 Ollama；`api.py` 通过 `monkeypatch` 替换 `recognizer.recognize` 避免在 api 层重复 mock httpx。
- **YAML 唯一数据源**：菜单改版时只改 `config/menus.yaml`，无代码改动；启动时校验确保配置错误立刻暴露。
- **失败豁免**：spec §11 列出的扩展项（追问话术、多会话、diff 工具、准确率面板）**不在本计划范围**，若实施中发现诱惑，立即返回 spec §1 "Out of scope"。
