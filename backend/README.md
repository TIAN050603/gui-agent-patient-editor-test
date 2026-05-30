# Browser Use 本地后端

这个目录提供本地 FastAPI 后端，用于把 Browser Use Python Agent 接到 GitHub Pages 上的“就诊人信息编辑系统”。

前端地址：

https://tian050603.github.io/gui-agent-patient-editor-test/

后端默认地址：

http://127.0.0.1:8000

## 1. 创建虚拟环境

```bash
cd backend
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
source .venv/bin/activate
```

## 2. 安装依赖

```bash
pip install -e .
```

## 3. 安装浏览器

Browser Use 使用 Playwright 驱动浏览器。首次运行前安装 Chromium：

```bash
playwright install chromium
```

如果你的系统提示缺少依赖，可参考 Playwright 提示安装系统依赖。

## 4. 配置 backend/.env

复制示例文件：

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

backend/.env 示例：

```env
LLM_PROVIDER=qwen
DASHSCOPE_API_KEY=你的真实key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-plus
```

注意：真实 key 只放在本地 `backend/.env`，不要提交到 GitHub。

也可以切换到 OpenAI：

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=你的真实key
OPENAI_MODEL=gpt-4o
```

## 5. 启动后端

```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

健康检查：

http://127.0.0.1:8000/api/health

## 6. 推荐测试流程

当前推荐主路径是 `Universal Form Agent`：

```text
中文自然语言任务 -> Qwen 解析 JSON plan -> 当前网页执行 plan -> 返回 steps 和 JSON 预览
```

1. 启动后端：

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --log-level debug
```

2. 测后端健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

3. 测 Qwen requests 直连：

```bash
curl http://127.0.0.1:8000/api/qwen/test
```

4. 打开前端页面：

```text
https://tian050603.github.io/gui-agent-patient-editor-test/
```

5. 在“自定义任务对话区”中选择 `Universal Form Agent`。

6. 输入中文自然语言任务并点击发送：

```text
请选择 P001 张伟，将手机号修改为 13912345678，然后点击保存。
```

如果成功，前端对话框会展示 Qwen 解析出的 plan、当前网页执行 steps 和页面 JSON 预览。

如果页面仍然默认显示 `Browser Use Agent`，说明浏览器还在使用旧版 GitHub Pages 缓存。请对前端页面执行强制刷新：

```text
Ctrl + F5
```

新版页面会默认选择 `Universal Form Agent`。

Universal Form Agent 成功响应中必须包含：

```json
{
  "llmUsed": true,
  "provider": "qwen",
  "model": "qwen-plus",
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

实际运行时 `usage.total_tokens` 应该大于 0，表示这次确实调用了 Qwen。

## 7. 调试顺序

如果 Browser Use Agent 卡住，请按下面顺序排查：

1. 先测后端是否启动：

```text
GET http://127.0.0.1:8000/api/health
```

预期返回：

```json
{
  "ok": true,
  "message": "Browser Use backend is running"
}
```

2. 再测千问 OpenAI-compatible 接口是否能通过 `requests` 直连：

```text
GET http://127.0.0.1:8000/api/qwen/test
```

这个接口不会调用 Browser Use，只会请求：

```text
POST {DASHSCOPE_BASE_URL}/chat/completions
```

如果成功，预期返回：

```json
{
  "ok": true,
  "provider": "qwen",
  "model": "qwen-plus",
  "content": "ok"
}
```

3. 推荐先测 Universal Form Agent：

```text
POST http://127.0.0.1:8000/api/universal-agent/plan
```

这个接口只调用 Qwen 解析 plan，不打开浏览器、不调用 Playwright、不使用 OpenAI SDK、ChatOpenAI 或 Browser Use。旧的 `/api/universal-agent/run` 只保留兼容用途，也会返回同样的 plan。

4. 最后再测 Browser Use Agent：

```text
POST http://127.0.0.1:8000/api/agent/run
```

如果 `/api/qwen/test` 成功但 `/api/agent/run` 卡住，后端会在 180 秒后返回：

```json
{
  "ok": false,
  "error": "Browser Use Agent 执行超时，可能卡在 Browser Use + ChatOpenAI/Qwen 层"
}
```

`/api/agent/run` 会把 Browser Use 放到独立 Python 子进程中运行。这样即使 Browser Use、浏览器层或 ChatOpenAI/Qwen 层出现非协作式阻塞，FastAPI 主进程也可以在 180 秒后强制终止子进程并返回错误。

Browser Use worker 的日志会以 `[browser-use-worker]` 前缀实时打印到 uvicorn 终端，便于判断它具体卡在浏览器启动、模型调用还是 Browser Use 内部动作。

5. 如果只想绕过 Qwen 解析做浏览器链路 smoke test，可以使用 Playwright Smoke Test：

```text
POST http://127.0.0.1:8000/api/quick-agent/run
```

这个接口不调用 Browser Use、不调用 Qwen、不调用 OpenAI SDK，只用 Playwright 直接操作测试页面。它只用于调试浏览器自动化链路，不是主 Agent。

启动 Browser Use 前，后端会打印以下调试信息，但不会打印 API Key：

```text
LLM_PROVIDER=...
DASHSCOPE_MODEL=...
DASHSCOPE_BASE_URL=...
```

## 8. 打开前端页面

打开：

https://tian050603.github.io/gui-agent-patient-editor-test/

## 9. 选择 Agent 模式

在“自定义任务对话区”中：

1. Agent 模式选择：`Universal Form Agent`
2. 后端地址保持：`http://127.0.0.1:8000`
3. 点击：`检查 Browser Use 后端连接`

如果连接成功，对话框会显示：

```text
Browser Use 后端连接成功。
```

可用模式：

- `本地规则 Agent`：纯前端规则解析。
- `Universal Form Agent`：推荐主路径，Qwen 解析 plan，当前网页执行页面操作。
- `Playwright Smoke Test`：只用于调试，不调用 Qwen，保留用于快速排查页面操作问题。
- `Browser Use Agent`：实验模式，可能受 Browser Use + 模型兼容性影响。

## 10. 输入测试任务

可以使用页面里的快捷示例，也可以手动输入：

```text
请选择 P001 张伟，将手机号修改为 13912345678，然后点击保存。
```

点击“发送任务”后，前端会调用：

```http
POST http://127.0.0.1:8000/api/universal-agent/plan
```

请求体：

```json
{
  "command": "请选择 P001 张伟，将手机号修改为 13912345678，然后点击保存。",
  "targetUrl": "https://tian050603.github.io/gui-agent-patient-editor-test/"
}
```

## 11. 查看执行结果

Universal Form Agent 会先让 Qwen 输出结构化 JSON plan。后端不会打开新浏览器，也不会修改页面；前端拿到 plan 后会在当前网页选择就诊人、编辑字段、点击保存，并把 plan、steps、preview 和错误信息显示在“自定义任务对话区”的对话历史里。

## 保留的测试任务

测试 1：

```text
请选择 P001 张伟，将手机号修改为 13912345678，然后点击保存。
```

测试 2：

```text
请选择 P002 李娜，将就诊科室修改为 消化内科，然后点击保存。
```

测试 3：

```text
请选择 P003 王强，将就诊类型修改为 复诊，然后点击保存。
```

测试 4：

```text
请选择 P004 陈敏，将就诊科室修改为 呼吸内科，将就诊类型修改为 复诊，将主诉/症状描述修改为 咳嗽、胸闷两天，然后点击保存。
```

测试 5：

```text
请选择 P005 赵磊，将手机号修改为 123，然后点击保存，观察页面是否提示手机号格式错误。
```

测试 6：

```text
请选择李娜，把医保类型改成自费，把备注改成需要复查，然后保存。
```

测试 7：

```text
打开王强的信息，把地址改成深圳市南山区科技园，不要保存。
```
