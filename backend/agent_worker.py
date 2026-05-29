import asyncio
import json
import sys
from pathlib import Path

from main import build_browser_use_task, build_llm, print_runtime_config, stringify_agent_result


async def run_agent(command: str, target_url: str) -> dict:
    try:
        from browser_use import Agent
    except ImportError:
        return {"ok": False, "error": "Browser Use 未安装，请先安装 backend 依赖。"}

    try:
        print_runtime_config()
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
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        if "playwright" in message.lower() or "browser" in message.lower():
            message = "浏览器未安装或无法启动，请先运行 playwright install chromium。原始错误：" + message
        return {"ok": False, "error": "Agent 执行失败：" + message}


def main() -> int:
    input_path = Path(sys.argv[1])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    output_path = Path(payload["outputPath"])
    result = asyncio.run(run_agent(payload["command"], payload["targetUrl"]))
    output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
