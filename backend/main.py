import os
from pathlib import Path
from typing import Any

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


def build_llm() -> Any:
    provider = os.getenv("LLM_PROVIDER", "qwen").strip().lower()

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
        return ChatOpenAI(
            model=os.getenv("DASHSCOPE_MODEL", "qwen-plus").strip() or "qwen-plus",
            api_key=api_key,
            base_url=os.getenv(
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ).strip()
            or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("未配置 OPENAI_API_KEY")
        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o",
            api_key=api_key,
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


@app.post("/api/agent/run")
async def run_agent(payload: AgentRunRequest) -> dict[str, Any]:
    command = payload.command.strip()
    if not command:
        return JSONResponse(status_code=400, content={"ok": False, "error": "command 不能为空"})

    target_url = normalize_target_url(payload.targetUrl)
    if target_url != ALLOWED_TARGET_URL:
        return JSONResponse(status_code=400, content={"ok": False, "error": "targetUrl 不被允许"})

    try:
        from browser_use import Agent
    except ImportError as exc:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Browser Use 未安装，请先安装 backend 依赖。"},
        )

    try:
        llm = build_llm()
        agent = Agent(task=build_browser_use_task(command, target_url), llm=llm)
        result = await agent.run()
        raw_result = stringify_agent_result(result)
        return {
            "ok": True,
            "summary": raw_result or "Agent 已执行完成，但未返回详细总结。",
            "rawResult": raw_result,
        }
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        if "playwright" in message.lower() or "browser" in message.lower():
            message = "浏览器未安装或无法启动，请先运行 playwright install chromium。原始错误：" + message
        return JSONResponse(status_code=500, content={"ok": False, "error": "Agent 执行失败：" + message})
