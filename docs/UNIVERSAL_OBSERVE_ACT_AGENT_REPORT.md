# Universal Observe-Act Agent 技术报告

本文档说明“就诊人信息编辑系统”中 Universal Observe-Act Agent 的工作流程、设计思路、前后端函数分工、每一轮 LLM 决策如何发生，以及它与 Browser Use Agent 的关系和区别。

当前 Universal Observe-Act Agent 是本项目的研究主线。它不是一次性把中文任务解析成完整 plan 后直接执行，而是采用类似浏览器 Agent 的多轮循环：

```text
用户输入中文任务
-> 前端观察当前网页状态
-> 后端调用 Qwen 决策下一步 action
-> 前端在当前网页执行 action
-> 前端再次观察页面
-> 后端再次调用 Qwen
-> 循环直到 LLM 输出 finish / ask_user / error
```

## 1. 设计目标

项目目标是验证 GUI/Web Agent 能否在一个真实网页界面中完成表单编辑任务。当前页面是静态单页应用，核心场景是：

```text
请选择 P001 张伟，将手机号修改为 13912345678，然后点击保存。
```

理想 Agent 需要具备以下能力：

- 读取当前网页中已选就诊人、表单字段、按钮、错误提示、保存结果预览等状态。
- 基于用户中文任务和当前页面状态决定下一步动作。
- 每次只执行一个动作，而不是一次性生成完整脚本。
- 动作执行后再次观察页面，确认页面是否变化。
- 若任务已完成，输出自然语言总结。
- 若信息不足，向用户追问。
- 若页面错误提示符合任务预期，例如手机号格式错误测试，则也能判断任务结束。

因此当前 Universal Observe-Act Agent 的核心不是“关键词解析”，而是“页面状态驱动的多轮 LLM 决策”。

## 2. 目前保留的 Agent 模式

页面中保留了多个模式，但定位不同：

| 模式 | 定位 | 是否主线 | 是否调用 LLM | 是否操作当前页面 |
|---|---|---:|---:|---:|
| Universal Observe-Act Agent | 当前主线，多轮观察、决策、动作 | 是 | 是，Qwen | 是 |
| Browser Use Agent | 实验模式，外部 browser-use 链路 | 否 | 是 | 否，通常控制外部浏览器 |
| Playwright Smoke Test | 浏览器自动化链路测试 | 否 | 否 | 否，后端 Playwright 打开页面 |
| 本地规则 Agent | 前端规则解析调试 | 否 | 否 | 是 |

Universal Observe-Act Agent 与 Browser Use 的思想相似，都是 observe -> decide -> act 循环；但 Universal 主链路没有直接调用 browser-use 开源代码，也不让后端打开新浏览器，而是让当前网页自己完成观察和动作。

## 3. 总体架构

### 3.1 组件分工

```text
index.html
  - 展示页面
  - 收集当前页面结构化状态 pageState
  - 调用后端 next-action 接口
  - 执行 LLM 返回的 action
  - 展示每轮 thought/action/usage/result

backend/main.py
  - 暴露 /api/universal-agent/next-action
  - 构造 Qwen prompt
  - 使用 requests 调用阿里云百炼 OpenAI-compatible API
  - 校验 Qwen 返回的 action JSON
  - 返回 action、usage、rawResponse

Qwen
  - 读取 command、pageState、history
  - 判断下一步 action
  - 不直接操作浏览器
```

### 3.2 关键接口

Universal 主线使用：

```http
POST http://127.0.0.1:8000/api/universal-agent/next-action
```

请求体：

```json
{
  "command": "请选择 P001 张伟，将手机号修改为 13912345678，然后点击保存。",
  "stepIndex": 0,
  "maxSteps": 10,
  "pageState": {},
  "history": []
}
```

响应体：

```json
{
  "ok": true,
  "mode": "universal-observe-act-agent",
  "llmUsed": true,
  "provider": "qwen",
  "model": "qwen-plus",
  "usage": {
    "prompt_tokens": 1000,
    "completion_tokens": 120,
    "total_tokens": 1120
  },
  "action": {
    "thought": "用户要求选择 P001 张伟，当前需要先选择该就诊人。",
    "type": "select_patient",
    "target": {
      "field": "patient",
      "selector": "#patientSelect",
      "label": "选择就诊人"
    },
    "value": "P001",
    "reason": "用户指定 P001 张伟",
    "done": false
  },
  "rawResponse": "{...}"
}
```

## 4. 前端工作流程

### 4.1 模式如何配置到页面

页面中 Agent 模式下拉框在 `index.html` 中定义：

```html
<select id="agentModeSelect" name="agentModeSelect" data-testid="agent-mode-select" aria-label="Agent 模式选择">
  <option value="universal" selected>Universal Observe-Act Agent（推荐）</option>
  <option value="browser-use">Browser Use Agent（实验模式，可能受 Browser Use + 模型兼容性影响）</option>
  <option value="playwright-quick">Playwright Smoke Test（仅用于测试浏览器自动化链路）</option>
  <option value="local">本地规则 Agent（仅用于调试）</option>
</select>
```

启动时前端也会明确设置默认模式：

```js
fields.agentMode.value = "universal";
```

发送按钮绑定：

```js
document.getElementById("sendAgentCommandButton").addEventListener("click", function () {
  executeAgentCommand(fields.agentCommandInput.value);
});
```

入口函数 `executeAgentCommand(commandText)` 会检查当前模式：

```js
if (fields.agentMode.value === "universal") {
  await executeUniversalFormCommand(command);
  return;
}
```

`executeUniversalFormCommand(command)` 只做一件事：进入 Universal Observe-Act 主循环。

```js
async function executeUniversalFormCommand(command) {
  await runUniversalObserveActAgent(command);
}
```

### 4.2 主循环函数：runUniversalObserveActAgent

`runUniversalObserveActAgent(command)` 是前端 Universal Agent 的核心调度器。

它负责：

1. 设置后端地址。
2. 设置最大步数 `maxSteps = 10`。
3. 初始化历史 `history = []`。
4. 初始化 token 统计 `totalUsage`。
5. 循环执行 observe -> LLM decide -> act。

核心结构如下：

```js
async function runUniversalObserveActAgent(command) {
  const backendUrl = getBrowserUseBackendUrl();
  const maxSteps = 10;
  const history = [];
  const totalUsage = {
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0
  };

  for (let stepIndex = 0; stepIndex < maxSteps; stepIndex += 1) {
    const pageState = collectCurrentPageState();

    const response = await fetch(backendUrl + "/api/universal-agent/next-action", {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=utf-8"
      },
      body: JSON.stringify({
        command: command,
        stepIndex: stepIndex,
        maxSteps: maxSteps,
        pageState: pageState,
        history: history
      })
    });

    const data = await response.json();
    addUsage(totalUsage, data.usage);

    const action = data.action;
    const actionResult = applyUniversalActionToCurrentPage(action);

    history.push({
      step: stepIndex,
      action: action,
      result: actionResult.message,
      pageStateSummary: summarizePageState(pageState)
    });

    if (["finish", "ask_user", "error"].includes(action.type)) {
      const finalState = collectCurrentPageState();
      appendChatMessage("agent", formatObserveActFinal(action, actionResult, finalState, totalUsage, history), ...);
      return;
    }
  }
}
```

### 4.3 observe：collectCurrentPageState

`collectCurrentPageState()` 是前端的观察函数。它不把整个 HTML DOM 发给模型，而是把页面整理成结构化 JSON，降低 token 消耗，并让模型更稳定理解当前页面。

它采集：

- 当前 URL 和标题。
- 当前选中的就诊人。
- 所有就诊人下拉选项。
- 每个表单字段的 label、type、value、selector、options。
- 可点击按钮。
- 当前错误提示和成功提示。
- 当前保存结果预览。

结构示例：

```js
function collectCurrentPageState() {
  const selectedOption = fields.patientSelect.options[fields.patientSelect.selectedIndex];
  return {
    url: window.location.href,
    title: document.title,
    selectedPatient: {
      value: fields.patientSelect.value,
      text: selectedOption ? selectedOption.textContent : ""
    },
    patientOptions: Array.from(fields.patientSelect.options).map(function (option) {
      return {
        value: option.value,
        text: option.textContent
      };
    }),
    fields: {
      phone: buildFieldState("手机号", "text", fields.phone, "#phoneInput"),
      department: buildFieldState("就诊科室", "select", fields.department, "#departmentSelect", getSelectOptions(fields.department)),
      visitType: {
        label: "就诊类型",
        type: "radio",
        value: getSelectedVisitType(),
        options: ["初诊", "复诊", "急诊"],
        selector: "input[name=\"visitType\"]"
      }
    },
    buttons: [
      { label: "保存修改", selector: "#saveButton" }
    ],
    messages: {
      errors: [],
      success: []
    },
    preview: fields.jsonPreview.textContent || "尚未保存任何修改。"
  };
}
```

### 4.4 decide：调用后端 next-action

前端每一轮都会调用：

```js
fetch(backendUrl + "/api/universal-agent/next-action", ...)
```

这一步不会执行任何页面动作，只是把当前页面状态和历史交给后端，再由后端请求 Qwen 决策下一步。

前端会强制检查：

```js
if (data.llmUsed !== true || !data.usage) {
  appendChatMessage("agent", "Universal Observe-Act Agent 异常：本轮没有确认 Qwen 调用或缺少 token usage。", "error");
  return;
}
```

这保证 Universal 主线不能退化成本地规则或伪 Agent。

### 4.5 act：applyUniversalActionToCurrentPage

`applyUniversalActionToCurrentPage(action)` 是当前页面动作执行器。它只操作当前网页 DOM，不使用 Playwright，也不打开新页面。

支持的 action 类型：

| action.type | 作用 |
|---|---|
| select_patient | 设置 `#patientSelect` 并触发 input/change |
| set_field | 设置 input/textarea/select |
| set_radio | 设置 radio |
| set_checkbox | 设置 checkbox |
| click_button | 点击按钮，例如 `#saveButton` |
| read_preview | 读取保存结果预览 |
| finish | 停止循环，展示最终结果 |
| ask_user | 停止循环，向用户追问 |
| error | 停止循环，展示错误 |

示例：

```js
if (action.type === "select_patient") {
  const patientId = String(action.value || "").toUpperCase();
  fields.patientSelect.value = patientId;
  fields.patientSelect.dispatchEvent(new Event("input", { bubbles: true }));
  fields.patientSelect.dispatchEvent(new Event("change", { bubbles: true }));
  return { success: true, message: "已在当前页面选择就诊人 " + patientId + "。" };
}
```

字段更新最终复用 `updateFormField(fieldKey, value)`：

```js
if (["set_field", "set_radio", "set_checkbox"].includes(action.type)) {
  const fieldKey = action.target && (action.target.field || resolveFieldKeyFromSelector(action.target.selector));
  const result = updateFormField(fieldKey, action.value);
  return { success: true, message: "已在当前页面修改" + getFieldDisplayName(fieldKey) + "为 " + result.displayValue + "。" };
}
```

点击保存：

```js
if (action.type === "click_button") {
  const selector = action.target && action.target.selector ? action.target.selector : "";
  const button = selector ? document.querySelector(selector) : null;
  button.click();
  return { success: true, message: "已点击当前页面按钮：保存修改。" };
}
```

### 4.6 history：为什么要保存历史

每轮执行后，前端会把 action 和执行结果写入 `history`：

```js
history.push({
  step: stepIndex,
  action: action,
  result: actionResult.message,
  pageStateSummary: summarizePageState(pageState)
});
```

history 有三个作用：

1. 让下一轮 Qwen 知道前面做过什么，避免重复动作。
2. 让最终摘要知道本次任务实际改动了哪些字段。
3. 让页面对话区可以展示完整执行轨迹。

### 4.7 final：最终回复如何生成

当 LLM 输出 `finish`、`ask_user` 或 `error` 时，前端停止循环，并调用：

```js
formatObserveActFinal(action, actionResult, finalState, totalUsage, history)
```

最终回复包含：

- LLM 自然语言完成总结。
- 本次任务结果摘要。
- 总 token usage。
- 当前页面保存结果预览。

其中“本次任务结果摘要”由 `buildTaskFocusedFinalSummary(finalState, history)` 生成。它只突出本轮实际改动字段：

```js
function buildTaskFocusedFinalSummary(finalState, history) {
  const changedFields = collectChangedFieldsFromHistory(history);
  const lines = [];

  if (changedFields.length > 0) {
    lines.push("本次重点更改：");
    changedFields.forEach(function (fieldKey) {
      const fieldState = finalState.fields[fieldKey];
      lines.push("- " + fieldState.label + "：" + formatFieldDisplayValue(fieldKey, fieldState.value));
    });
  }

  const unchangedLabels = Object.keys(finalState.fields)
    .filter(function (fieldKey) {
      return !changedFields.includes(fieldKey);
    })
    .map(function (fieldKey) {
      return finalState.fields[fieldKey].label;
    });

  lines.push("未更改字段：" + unchangedLabels.join("、") + "。");
  return lines.join("\n");
}
```

这避免了最终回答中反复罗列大量未涉及字段。

## 5. 后端工作流程

后端文件是 `backend/main.py`。

### 5.1 请求模型：UniversalNextActionRequest

后端定义了 `/api/universal-agent/next-action` 的请求体：

```python
class UniversalNextActionRequest(BaseModel):
    command: str = Field(..., description="用户原始中文自然语言任务")
    stepIndex: int = Field(0, description="当前 observe-act 步数，从 0 开始")
    maxSteps: int = Field(10, description="最大执行步数")
    pageState: dict[str, Any] = Field(default_factory=dict, description="前端采集的当前页面结构化状态")
    history: list[dict[str, Any]] = Field(default_factory=list, description="之前 action 与执行结果历史")
```

关键点：

- `command` 是用户原始任务，不在前端做规则解析。
- `stepIndex` 告诉 Qwen 当前是第几轮。
- `maxSteps` 告诉 Qwen 最多能执行多少轮。
- `pageState` 是当前页面观察结果。
- `history` 是之前动作和结果。

### 5.2 Prompt 构造：build_next_action_prompt

`build_next_action_prompt(payload)` 负责构造 Qwen 的 system/user messages。

核心要求：

- 你是当前网页表单 GUI Agent 的决策器。
- 你不会直接操作浏览器。
- 每轮只输出一个下一步 action。
- 不要一次性输出完整计划。
- 如果用户明确要求选择某个就诊人，先输出 `select_patient`。
- 如果输入只是片段，输出 `ask_user`。
- 如果字段没到目标值，输出对应设置动作。
- 如果用户要求保存且字段已改好，输出 `click_button`。
- 如果保存结果或错误提示符合任务，输出 `finish`。

片段示例：

```python
system_prompt = (
    "你是一个当前网页表单 GUI Agent 的决策器。你不会直接操作浏览器，只根据用户任务、当前页面状态 pageState 和历史 history，输出下一步 action JSON。"
    "必须逐步执行，每轮只输出一个下一步 action，不要一次性输出完整计划。"
    "如果用户输入只是姓名、编号、电话号码等片段，缺少明确动作意图，不要猜测执行，应输出 ask_user 请求确认。"
    "如果用户要求保存且字段已改好，输出 click_button；如果保存后错误提示符合用户预期或保存结果预览已符合任务，输出 finish。"
)
```

### 5.3 Qwen 调用：call_qwen_for_next_action

`call_qwen_for_next_action(payload)` 使用 `requests` 调用阿里云百炼 OpenAI-compatible API。

它没有使用 OpenAI SDK，也没有使用 ChatOpenAI，原因是本项目中 requests 直连 Qwen 更稳定。

核心调用：

```python
response = requests.post(
    url,
    headers={
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json; charset=utf-8",
    },
    json={
        "model": model,
        "messages": build_next_action_prompt(payload),
        "temperature": 0,
    },
    timeout=30,
)
```

返回内容会解析出：

- `action`
- `rawResponse`
- `usage.prompt_tokens`
- `usage.completion_tokens`
- `usage.total_tokens`
- `llmUsed = True`

如果 Qwen 没有返回合法 JSON，则返回错误，不允许前端执行动作。

### 5.4 Action 校验：validate_universal_action

`validate_universal_action(action)` 是后端安全边界。

它检查：

- action 必须是 JSON object。
- `type` 必须在允许列表中。
- 需要 target 的动作必须提供 target。
- 字段类动作必须对应已知字段。
- select/radio 字段的 value 必须在 options 范围内。
- checkbox 字段必须是 boolean。

允许的 action：

```python
allowed_types = {
    "select_patient",
    "set_field",
    "set_radio",
    "set_checkbox",
    "click_button",
    "read_preview",
    "finish",
    "ask_user",
    "error",
}
```

它还支持 selector 到字段的映射：

```python
SELECTOR_TO_FIELD = {
    "#phoneInput": "phone",
    "#departmentSelect": "department",
    "#symptomsTextarea": "symptoms",
    "#remarkTextarea": "remark",
}
```

这样即使 Qwen 返回 `selector` 而没有返回 `field`，后端也可以把它标准化为字段 key。

### 5.5 API 入口：next_universal_agent_action

接口函数：

```python
@app.post("/api/universal-agent/next-action", response_model=None)
async def next_universal_agent_action(payload: UniversalNextActionRequest):
```

执行顺序：

1. 校验 `command` 不能为空。
2. 校验 `pageState` 不能为空。
3. 调用 `call_qwen_for_next_action(payload)`。
4. 如果没有调用 LLM，返回失败。
5. 如果 Qwen 输出非法 JSON，返回失败。
6. 调用 `validate_universal_action(action)`。
7. 返回标准响应。

成功响应：

```python
return utf8_json(
    {
        "ok": True,
        "mode": "universal-observe-act-agent",
        "llmUsed": True,
        "provider": "qwen",
        "model": llm_info.get("model"),
        "usage": llm_info.get("usage"),
        "action": validated_action,
        "rawResponse": raw_response,
    },
    200,
)
```

## 6. Observe-Act 轮次是怎么定的

### 6.1 当前固定最大轮次

当前前端写死：

```js
const maxSteps = 10;
```

并使用：

```js
for (let stepIndex = 0; stepIndex < maxSteps; stepIndex += 1) {
  ...
}
```

也就是说，一次任务最多允许 10 轮 LLM 决策。

### 6.2 每一轮何时开始

每轮开始时，前端先调用：

```js
const pageState = collectCurrentPageState();
```

这保证每一轮 Qwen 看到的是动作执行后的最新页面状态，而不是旧状态。

### 6.3 每一轮何时结束

每轮结束于以下之一：

1. action 执行成功，继续下一轮。
2. action 执行失败，停止并显示错误。
3. Qwen 输出 `finish`，停止并显示完成总结。
4. Qwen 输出 `ask_user`，停止并显示追问。
5. Qwen 输出 `error`，停止并显示错误。
6. 达到 `maxSteps = 10`，停止并显示“达到最大执行步数，任务未确认完成”。

### 6.4 为什么是 10 轮

10 轮是一个工程折中：

- 测试 1 这类任务通常需要 4 轮：选择就诊人、修改字段、保存、完成。
- 测试 4 多字段任务可能需要 6 到 8 轮：选择就诊人、改科室、改就诊类型、改主诉、保存、完成。
- 10 轮足够覆盖当前表单测试任务。
- 同时避免模型陷入循环导致无限请求和 token 浪费。

未来可以把 `maxSteps` 配置为 UI 输入项或后端策略项，但目前固定在前端，便于实验可控。

## 7. 示例任务的多轮过程

任务：

```text
请选择 P001 张伟，将手机号修改为 13912345678，然后点击保存。
```

可能的过程：

### 第 1 轮

前端观察：

```json
{
  "selectedPatient": {
    "value": "P001",
    "text": "P001 - 张伟 - 呼吸内科"
  },
  "fields": {
    "phone": {
      "value": "13800010001"
    }
  }
}
```

Qwen action：

```json
{
  "thought": "用户明确要求选择 P001 张伟，先执行选择就诊人动作。",
  "type": "select_patient",
  "target": {
    "field": "patient",
    "selector": "#patientSelect",
    "label": "选择就诊人"
  },
  "value": "P001",
  "reason": "用户指定 P001 张伟",
  "done": false
}
```

前端执行：设置 `#patientSelect` 为 `P001` 并触发 change。

### 第 2 轮

Qwen 观察到 P001 已选中，但手机号未改。

Qwen action：

```json
{
  "thought": "当前已选中 P001，下一步修改手机号。",
  "type": "set_field",
  "target": {
    "field": "phone",
    "selector": "#phoneInput",
    "label": "手机号"
  },
  "value": "13912345678",
  "reason": "用户要求将手机号修改为 13912345678",
  "done": false
}
```

前端执行：修改 `#phoneInput` 并触发 input/change。

### 第 3 轮

Qwen 观察到手机号已正确，但用户要求保存。

Qwen action：

```json
{
  "thought": "手机号已经修改完成，用户要求保存。",
  "type": "click_button",
  "target": {
    "field": "save",
    "selector": "#saveButton",
    "label": "保存修改"
  },
  "value": null,
  "reason": "用户要求点击保存",
  "done": false
}
```

前端执行：点击保存按钮。

### 第 4 轮

Qwen 观察到保存成功提示和保存结果预览。

Qwen action：

```json
{
  "thought": "保存结果预览中手机号已经是 13912345678，任务完成。",
  "type": "finish",
  "target": null,
  "value": "已将 P001 张伟的手机号修改为 13912345678 并保存成功。",
  "reason": "页面状态与用户任务一致",
  "done": true
}
```

前端停止循环并展示最终回复。

## 8. 与 Browser Use 的关系和区别

### 8.1 借鉴点

Universal Observe-Act Agent 借鉴了 Browser Use / 浏览器 Agent 的核心思想：

```text
observe -> decide -> act -> observe again
```

也借鉴了以下概念：

- history：记录每轮动作和结果。
- max steps：限制最大执行步数。
- done 判断：由模型输出 finish。
- action schema：模型输出结构化动作，而不是任意文本。

### 8.2 没有直接复用 browser-use 代码

Universal 主链路没有直接调用 browser-use 的 Agent，也没有使用 browser-use 控制浏览器。

原因：

- 本项目要求操作当前网页，而不是打开后端新浏览器。
- 当前 browser-use + Qwen/OpenAI-compatible 链路曾出现阻塞。
- 当前测试页结构固定，前端可以直接采集结构化状态，更稳定、更可控。

### 8.3 核心区别

| 维度 | Universal Observe-Act Agent | Browser Use Agent |
|---|---|---|
| 页面观察 | 前端手写结构化 `pageState` | browser-use 内部观察浏览器 |
| 决策 | 后端 requests 调 Qwen | browser-use 模型层 |
| 动作执行 | 当前网页 JS DOM 操作 | Playwright/浏览器自动化 |
| 是否打开新页面 | 不打开 | 通常打开或控制浏览器页面 |
| 范围 | 专用于就诊人表单研究页 | 通用网页 Agent |
| 可控性 | 高，字段和动作 schema 固定 | 更通用但变量更多 |
| 调试 | 对话区显示每轮 action、usage、结果 | 依赖 browser-use 日志 |

## 9. 当前设计优点

- 动作确实发生在用户当前看到的网页上。
- 每一步都必须调用 Qwen，避免退化成规则脚本。
- 每一轮 action 都显示在对话区，便于研究 GUI Agent 行为。
- pageState 是结构化 JSON，比完整 DOM 更省 token。
- 后端只负责模型决策，不碰浏览器，稳定性更好。
- 前端动作执行器可控，适合构造 GUI agent 测试基准。

## 10. 当前限制

- pageState 是人工设计的页面摘要，不是通用 DOM 观察器。
- action schema 专门服务当前就诊人表单，不是通用网页操作语言。
- maxSteps 目前固定为 10。
- 对“任务是否完成”的判断依赖 Qwen 对 pageState、messages、preview 的理解。
- 如果 Qwen 输出重复 action，仍可能耗尽 maxSteps。

## 11. 后续可扩展方向

可以继续研究：

- 增加 loop guard，检测重复 action 并提示 Qwen 修正。
- 将 maxSteps 变成页面可配置项。
- 给 pageState 增加字段变更 diff，让 Qwen 更容易判断任务进度。
- 增加 action confidence。
- 支持 ask_user 后继续同一个 history 会话。
- 将 action schema 抽象成更通用的网页表单操作协议。
- 增加自动测试脚本，验证五个标准任务的 observe-act 路径是否符合预期。

## 12. 总结

Universal Observe-Act Agent 是一个面向当前网页的轻量级 GUI Agent 架构。它不依赖 browser-use 控制浏览器，但复用了浏览器 Agent 的核心思想：

```text
观察页面 -> 模型决策 -> 执行动作 -> 再观察
```

它的核心价值是：让 LLM 每一步都基于真实页面状态做决策，并让动作直接作用在用户当前看到的页面上。这使它比“一次性 plan”更接近真实 GUI Agent，也比后端 Playwright 打开新页面更符合本项目的研究目标。
