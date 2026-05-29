import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


BACKEND_DIR = Path(__file__).resolve().parent
ALLOWED_TARGET_URL = "https://tian050603.github.io/gui-agent-patient-editor-test/"

load_dotenv(BACKEND_DIR / ".env")

app = FastAPI(title="GUI Agent Browser Use Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://tian050603.github.io",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentRunRequest(BaseModel):
    command: str = Field(..., description="用户输入的自然语言任务")
    targetUrl: str = Field(..., description="允许 Browser Use 访问的目标页面 URL")


def normalize_target_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    return url if url.endswith("/") else url + "/"


def get_provider_name() -> str:
    return os.getenv("LLM_PROVIDER", "qwen").strip().lower()


def get_dashscope_base_url() -> str:
    return (
        os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def get_dashscope_model() -> str:
    return os.getenv("DASHSCOPE_MODEL", "qwen-plus").strip() or "qwen-plus"


def print_runtime_config() -> None:
    print("LLM_PROVIDER=" + get_provider_name(), flush=True)
    print("DASHSCOPE_MODEL=" + get_dashscope_model(), flush=True)
    print("DASHSCOPE_BASE_URL=" + get_dashscope_base_url(), flush=True)


def create_chat_openai(ChatOpenAI: Any, kwargs: dict[str, Any]) -> Any:
    try:
        import httpx

        sync_client = httpx.Client(trust_env=False, timeout=30)
        async_client = httpx.AsyncClient(trust_env=False, timeout=30)
        try:
            return ChatOpenAI(**kwargs, http_client=sync_client, http_async_client=async_client)
        except TypeError:
            sync_client.close()
            asyncio.create_task(async_client.aclose())
            # Some ChatOpenAI implementations or browser-use wrappers may not expose
            # http_client/http_async_client. In that case we still set timeout and
            # max_retries, but cannot force trust_env=False at the client object level.
            return ChatOpenAI(**kwargs)
    except ImportError:
        return ChatOpenAI(**kwargs)


def build_llm() -> Any:
    provider = get_provider_name()

    try:
        from browser_use import ChatOpenAI
    except ImportError:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("Browser Use 或 langchain-openai 未安装，无法导入 ChatOpenAI。") from exc

    if provider == "qwen":
        api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY")
        return create_chat_openai(
            ChatOpenAI,
            {
                "model": get_dashscope_model(),
                "api_key": api_key,
                "base_url": get_dashscope_base_url(),
                "timeout": 30,
                "max_retries": 0,
            },
        )

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("未配置 OPENAI_API_KEY")
        return create_chat_openai(
            ChatOpenAI,
            {
                "model": os.getenv("OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o",
                "api_key": api_key,
                "timeout": 30,
                "max_retries": 0,
            },
        )

    raise RuntimeError("不支持的 LLM_PROVIDER：" + provider)


def build_browser_use_task(command: str, target_url: str) -> str:
    return f"""
你是一个浏览器 GUI Agent。
请打开：
{target_url}

用户任务是：
{command}

你需要完成：
- 选择正确的就诊人
- 修改指定字段
- 如果用户要求保存，则点击“保存修改”
- 检查页面下方“当前保存结果 JSON 预览”
- 最后用中文总结是否执行成功

请优先通过页面上的 label、aria-label、id、data-testid 定位元素。
不要输入真实个人信息。
只操作这个测试页面。
""".strip()


def stringify_agent_result(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if hasattr(result, "final_result"):
        try:
            final_result = result.final_result()
            if final_result:
                return str(final_result)
        except Exception:
            pass
    if hasattr(result, "model_dump_json"):
        try:
            return result.model_dump_json(indent=2)
        except Exception:
            pass
    if hasattr(result, "model_dump"):
        try:
            return str(result.model_dump())
        except Exception:
            pass
    return str(result)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "message": "Browser Use backend is running"}


@app.get("/api/qwen/test")
async def test_qwen() -> dict[str, Any] | JSONResponse:
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return JSONResponse(status_code=400, content={"ok": False, "error": "未配置 DASHSCOPE_API_KEY"})

    model = get_dashscope_model()
    base_url = get_dashscope_base_url().rstrip("/")
    url = base_url + "/chat/completions"

    try:
        response = requests.post(
            url,
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "只回复 ok"}],
            },
            timeout=20,
        )
        if response.status_code >= 400:
            return JSONResponse(
                status_code=response.status_code,
                content={
                    "ok": False,
                    "error": "Qwen test failed: HTTP "
                    + str(response.status_code)
                    + " "
                    + response.text[:500],
                },
            )
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {
            "ok": True,
            "provider": "qwen",
            "model": model,
            "content": content,
        }
    except requests.Timeout:
        return JSONResponse(status_code=504, content={"ok": False, "error": "Qwen test timeout after 20 seconds"})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": "Qwen test failed: " + str(exc)})


def sanitize_log(text: str) -> str:
    if not text:
        return ""
    secrets = [
        os.getenv("DASHSCOPE_API_KEY", "").strip(),
        os.getenv("OPENAI_API_KEY", "").strip(),
    ]
    sanitized = text
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "***REDACTED***")
    return sanitized[-4000:]


def run_browser_use_agent_subprocess(command: str, target_url: str, timeout_seconds: int = 180) -> dict[str, Any]:
    worker_path = BACKEND_DIR / "agent_worker.py"
    with tempfile.TemporaryDirectory(prefix="browser-use-agent-") as temp_dir:
        input_path = Path(temp_dir) / "input.json"
        output_path = Path(temp_dir) / "output.json"
        input_path.write_text(
            json.dumps(
                {
                    "command": command,
                    "targetUrl": target_url,
                    "outputPath": str(output_path),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        process = subprocess.Popen(
            [sys.executable, str(worker_path), str(input_path)],
            cwd=str(BACKEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=10)
            return {
                "ok": False,
                "error": "Browser Use Agent 执行超时，可能是 OpenAI-compatible SDK 或模型调用层卡住",
                "debugLog": sanitize_log((stdout or "") + "\n" + (stderr or "")),
            }

        debug_log = sanitize_log((stdout or "") + "\n" + (stderr or ""))
        if output_path.exists():
            try:
                result = json.loads(output_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return {
                    "ok": False,
                    "error": "Agent worker 返回了无法解析的 JSON：" + str(exc),
                    "debugLog": debug_log,
                }
            if debug_log and "debugLog" not in result:
                result["debugLog"] = debug_log
            return result

        return {
            "ok": False,
            "error": "Agent worker 未生成结果，退出码：" + str(process.returncode),
            "debugLog": debug_log,
        }


@app.post("/api/agent/run")
async def run_agent(payload: AgentRunRequest) -> dict[str, Any]:
    command = payload.command.strip()
    if not command:
        return JSONResponse(status_code=400, content={"ok": False, "error": "command 不能为空"})

    target_url = normalize_target_url(payload.targetUrl)
    if target_url != ALLOWED_TARGET_URL:
        return JSONResponse(status_code=400, content={"ok": False, "error": "targetUrl 不被允许"})

    try:
        print_runtime_config()
        result = await asyncio.to_thread(run_browser_use_agent_subprocess, command, target_url, 180)
        status_code = 200 if result.get("ok") else 504 if "超时" in result.get("error", "") else 500
        return JSONResponse(status_code=status_code, content=result)
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        if "playwright" in message.lower() or "browser" in message.lower():
            message = "浏览器未安装或无法启动，请先运行 playwright install chromium。原始错误：" + message
        return JSONResponse(status_code=500, content={"ok": False, "error": "Agent 执行失败：" + message})
