# -*- coding: utf-8 -*-
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
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
UTF8_JSON = "application/json; charset=utf-8"

FIELD_SCHEMA: dict[str, dict[str, Any]] = {
    "name": {"label": "姓名", "selectors": ["#nameInput", '[data-testid="name-input"]', 'input[name="name"]', '[aria-label="姓名"]'], "kind": "text"},
    "gender": {"label": "性别", "selectors": ["#genderSelect", '[data-testid="gender-select"]', 'select[name="gender"]', '[aria-label="性别"]'], "kind": "select", "options": ["男", "女", "其他"]},
    "age": {"label": "年龄", "selectors": ["#ageInput", '[data-testid="age-input"]', 'input[name="age"]', '[aria-label="年龄"]'], "kind": "text"},
    "birthDate": {"label": "出生日期", "selectors": ["#birthDateInput", '[data-testid="birth-date-input"]', 'input[name="birthDate"]', '[aria-label="出生日期"]'], "kind": "text"},
    "phone": {"label": "手机号", "selectors": ["#phoneInput", '[data-testid="phone-input"]', 'input[name="phone"]', '[aria-label="手机号"]'], "kind": "text"},
    "idType": {"label": "证件类型", "selectors": ["#idTypeSelect", '[data-testid="id-type-select"]', 'select[name="idType"]', '[aria-label="证件类型"]'], "kind": "select", "options": ["身份证", "护照", "港澳通行证", "其他"]},
    "idNumber": {"label": "证件号码", "selectors": ["#idNumberInput", '[data-testid="id-number-input"]', 'input[name="idNumber"]', '[aria-label="证件号码"]'], "kind": "text"},
    "address": {"label": "地址", "selectors": ["#addressInput", '[data-testid="address-input"]', 'input[name="address"]', '[aria-label="地址"]'], "kind": "text"},
    "emergencyContact": {"label": "紧急联系人", "selectors": ["#emergencyContactInput", '[data-testid="emergency-contact-input"]', 'input[name="emergencyContact"]', '[aria-label="紧急联系人"]'], "kind": "text"},
    "emergencyPhone": {"label": "紧急联系人电话", "selectors": ["#emergencyPhoneInput", '[data-testid="emergency-phone-input"]', 'input[name="emergencyPhone"]', '[aria-label="紧急联系人电话"]'], "kind": "text"},
    "department": {"label": "就诊科室", "selectors": ["#departmentSelect", '[data-testid="department-select"]', 'select[name="department"]', '[aria-label="就诊科室"]'], "kind": "select", "options": ["呼吸内科", "消化内科", "心血管内科", "神经内科", "骨科", "皮肤科", "儿科", "眼科", "耳鼻喉科", "急诊科"]},
    "visitType": {"label": "就诊类型", "selectors": ['input[name="visitType"]'], "kind": "radio", "options": ["初诊", "复诊", "急诊"]},
    "insuranceType": {"label": "医保类型", "selectors": ["#insuranceTypeSelect", '[data-testid="insurance-type-select"]', 'select[name="insuranceType"]', '[aria-label="医保类型"]'], "kind": "select", "options": ["城镇职工医保", "城乡居民医保", "商业保险", "自费", "其他"]},
    "hasAllergy": {"label": "是否有过敏史", "selectors": ["#hasAllergyCheckbox", '[data-testid="has-allergy-checkbox"]', 'input[name="hasAllergy"]', '[aria-label="是否有过敏史"]'], "kind": "checkbox"},
    "allergyNote": {"label": "过敏史说明", "selectors": ["#allergyNoteTextarea", '[data-testid="allergy-note-textarea"]', 'textarea[name="allergyNote"]', '[aria-label="过敏史说明"]'], "kind": "text"},
    "medicalHistory": {"label": "既往病史", "selectors": ["#medicalHistoryTextarea", '[data-testid="medical-history-textarea"]', 'textarea[name="medicalHistory"]', '[aria-label="既往病史"]'], "kind": "text"},
    "symptoms": {"label": "主诉/症状描述", "selectors": ["#symptomsTextarea", '[data-testid="symptoms-textarea"]', 'textarea[name="symptoms"]', '[aria-label="主诉/症状描述"]'], "kind": "text"},
    "remark": {"label": "备注", "selectors": ["#remarkTextarea", '[data-testid="remark-textarea"]', 'textarea[name="remark"]', '[aria-label="备注"]'], "kind": "text"},
}

SELECTOR_TO_FIELD = {
    "#nameInput": "name",
    "#genderSelect": "gender",
    "#ageInput": "age",
    "#birthDateInput": "birthDate",
    "#phoneInput": "phone",
    "#idTypeSelect": "idType",
    "#idNumberInput": "idNumber",
    "#addressInput": "address",
    "#emergencyContactInput": "emergencyContact",
    "#emergencyPhoneInput": "emergencyPhone",
    "#departmentSelect": "department",
    "#insuranceTypeSelect": "insuranceType",
    "#hasAllergyCheckbox": "hasAllergy",
    "#allergyNoteTextarea": "allergyNote",
    "#medicalHistoryTextarea": "medicalHistory",
    "#symptomsTextarea": "symptoms",
    "#remarkTextarea": "remark",
}

PATIENT_NAME_TO_ID = {
    "张伟": "P001",
    "李娜": "P002",
    "王强": "P003",
    "陈敏": "P004",
    "赵磊": "P005",
}

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


class UniversalNextActionRequest(BaseModel):
    command: str = Field(..., description="用户原始中文自然语言任务")
    stepIndex: int = Field(0, description="当前 observe-act 步数，从 0 开始")
    maxSteps: int = Field(10, description="最大执行步数")
    pageState: dict[str, Any] = Field(default_factory=dict, description="前端采集的当前页面结构化状态")
    history: list[dict[str, Any]] = Field(default_factory=list, description="之前 action 与执行结果历史")


class Utf8JSONResponse(JSONResponse):
    media_type = UTF8_JSON

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")


def utf8_json(content: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return Utf8JSONResponse(status_code=status_code, content=content)


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


def print_worker_log(prefix: str, text: str) -> None:
    if not text:
        return
    safe_text = sanitize_log(text.rstrip())
    if safe_text:
        print(prefix + safe_text, flush=True)


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
- 检查页面下方“当前保存结果预览”
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


@app.get("/api/health", response_model=None)
async def health():
    return utf8_json({"ok": True, "message": "Browser Use backend is running"})


@app.get("/api/qwen/test", response_model=None)
async def test_qwen():
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return utf8_json({"ok": False, "error": "未配置 DASHSCOPE_API_KEY"}, 400)

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
            return utf8_json(
                {
                    "ok": False,
                    "error": "Qwen test failed: HTTP "
                    + str(response.status_code)
                    + " "
                    + response.text[:500],
                },
                response.status_code,
            )
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return utf8_json({"ok": True, "provider": "qwen", "model": model, "content": content})
    except requests.Timeout:
        return utf8_json({"ok": False, "error": "Qwen test timeout after 20 seconds"}, 504)
    except Exception as exc:
        return utf8_json({"ok": False, "error": "Qwen test failed: " + str(exc)}, 500)


def build_plan_prompt(command: str) -> list[dict[str, str]]:
    schema = {
        "patient": {"patientId": "P001", "name": "张伟"},
        "updates": {field: None for field in FIELD_SCHEMA},
        "save": True,
        "intent": "edit_patient",
        "confidence": 0.95,
    }
    system_prompt = (
        "你是一个医疗测试表单任务解析器。你只把用户中文任务解析成 JSON plan。"
        "只输出合法 JSON，不要输出 markdown，不要输出解释。"
        "字段只能使用给定 schema 中的 key。未修改字段必须为 null。"
        "save 只有在用户明确要求保存、提交、点击保存、然后保存时才为 true；用户说不要保存时必须为 false。"
        "可选值必须严格使用这些中文值："
        "gender=男/女/其他；idType=身份证/护照/港澳通行证/其他；"
        "department=呼吸内科/消化内科/心血管内科/神经内科/骨科/皮肤科/儿科/眼科/耳鼻喉科/急诊科；"
        "visitType=初诊/复诊/急诊；insuranceType=城镇职工医保/城乡居民医保/商业保险/自费/其他；"
        "hasAllergy=true/false。"
    )
    user_prompt = (
        "请解析这个任务：\n"
        + command
        + "\n\n严格输出这个 JSON schema，字段齐全，未修改字段填 null：\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def call_qwen_for_plan(command: str) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any]]:
    llm_info = {
        "llmUsed": False,
        "provider": "qwen",
        "model": get_dashscope_model(),
        "usage": None,
    }
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return None, "", "未配置 DASHSCOPE_API_KEY", llm_info

    model = get_dashscope_model()
    url = get_dashscope_base_url().rstrip("/") + "/chat/completions"
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "model": model,
                "messages": build_plan_prompt(command),
                "temperature": 0,
            },
            timeout=30,
        )
        llm_info["llmUsed"] = True
    except requests.Timeout:
        return None, "", "Qwen 解析任务超时", llm_info
    except Exception as exc:
        return None, "", "Qwen 解析任务失败：" + str(exc), llm_info

    raw_body = response.text
    if response.status_code >= 400:
        return None, raw_body, "Qwen 解析任务失败：HTTP " + str(response.status_code), llm_info

    try:
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage") or {}
        llm_info["usage"] = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
    except Exception as exc:
        return None, raw_body, "Qwen 返回不是合法响应 JSON：" + str(exc), llm_info

    raw_content = (content or "").strip()
    try:
        return json.loads(raw_content), raw_content, None, llm_info
    except json.JSONDecodeError:
        return None, raw_content, "Qwen 没有返回合法 JSON", llm_info


def build_next_action_prompt(payload: UniversalNextActionRequest) -> list[dict[str, str]]:
    action_schema = {
        "thought": "简短说明为什么下一步这样做",
        "type": "select_patient | set_field | set_radio | set_checkbox | click_button | read_preview | finish | ask_user | error",
        "target": {
            "field": "phone",
            "selector": "#phoneInput",
            "label": "手机号",
        },
        "value": "13912345678",
        "reason": "当前任务要求修改 P001 的手机号",
        "done": False,
    }
    system_prompt = (
        "你是一个当前网页表单 GUI Agent 的决策器。你不会直接操作浏览器，只根据用户任务、当前页面状态 pageState 和历史 history，输出下一步 action JSON。"
        "必须逐步执行，每轮只输出一个下一步 action，不要一次性输出完整计划。"
        "如果用户明确说“请选择、选择、打开、切换到”某个就诊人，且 history 中还没有对应 select_patient action，即使当前已经选中该就诊人，也先输出 select_patient。"
        "如果用户输入只是姓名、编号、电话号码等片段，缺少明确动作意图，不要猜测执行，应输出 ask_user 请求确认。"
        "你必须先观察 pageState：如果目标就诊人未选中，先输出 select_patient；如果字段未达到目标值，输出 set_field/set_radio/set_checkbox；"
        "如果用户要求保存且字段已改好，输出 click_button；如果保存后错误提示符合用户预期或保存结果预览已符合任务，输出 finish。"
        "输出 finish 时，reason 或 value 必须是给用户看的自然语言完成总结，例如：已将 P001 张伟的手机号修改为 13912345678 并保存成功。"
        "如果用户任务缺少必要信息，输出 ask_user；如果页面状态无法支持任务，输出 error。"
        "只输出合法 JSON，不要 markdown，不要解释，不要包裹代码块。"
        "可用 action.type 只有：select_patient、set_field、set_radio、set_checkbox、click_button、read_preview、finish、ask_user、error。"
        "可用字段 key 只有：name、gender、age、birthDate、phone、idType、idNumber、address、emergencyContact、emergencyPhone、department、visitType、insuranceType、hasAllergy、allergyNote、medicalHistory、symptoms、remark。"
        "选择就诊人时 value 使用 patientOptions 中的 value，例如 P001。"
        "修改 select/radio 字段时 value 必须使用 pageState.fields[field].options 中存在的值。"
        "点击保存按钮时 target.selector 使用 #saveButton。"
        "手机号格式错误测试中，如果保存后页面 errors 包含手机号格式错误，应视为观察目标达成并 finish。"
        "输出 JSON schema 如下："
        + json.dumps(action_schema, ensure_ascii=False)
    )
    user_prompt = json.dumps(
        {
            "command": payload.command,
            "stepIndex": payload.stepIndex,
            "maxSteps": payload.maxSteps,
            "pageState": payload.pageState,
            "history": payload.history,
        },
        ensure_ascii=False,
        indent=2,
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def call_qwen_for_next_action(payload: UniversalNextActionRequest) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any]]:
    llm_info = {
        "llmUsed": False,
        "provider": "qwen",
        "model": get_dashscope_model(),
        "usage": None,
    }
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return None, "", "未配置 DASHSCOPE_API_KEY", llm_info

    model = get_dashscope_model()
    url = get_dashscope_base_url().rstrip("/") + "/chat/completions"
    try:
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
        llm_info["llmUsed"] = True
    except requests.Timeout:
        return None, "", "Qwen 决策下一步 action 超时", llm_info
    except Exception as exc:
        return None, "", "Qwen 决策下一步 action 失败：" + str(exc), llm_info

    raw_body = response.text
    if response.status_code >= 400:
        return None, raw_body, "Qwen 决策下一步 action 失败：HTTP " + str(response.status_code), llm_info

    try:
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage") or {}
        llm_info["usage"] = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
    except Exception as exc:
        return None, raw_body, "Qwen 返回不是合法响应 JSON：" + str(exc), llm_info

    raw_content = (content or "").strip()
    try:
        return json.loads(raw_content), raw_content, None, llm_info
    except json.JSONDecodeError:
        return None, raw_content, "Qwen 没有返回合法 action JSON", llm_info


def validate_universal_action(action: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(action, dict):
        return None, "Qwen action 不是 JSON object"

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
    action_type = action.get("type")
    if action_type not in allowed_types:
        return None, "不支持的 action.type：" + str(action_type)

    target = action.get("target")
    if target is not None and not isinstance(target, dict):
        return None, "target 必须是 object 或 null"

    if action_type in {"select_patient", "set_field", "set_radio", "set_checkbox", "click_button"}:
        if not isinstance(target, dict):
            return None, action_type + " 必须提供 target"
        if not target.get("selector") and not target.get("field"):
            return None, action_type + " 的 target 至少需要 selector 或 field"

    if action_type in {"set_field", "set_radio", "set_checkbox"}:
        field = target.get("field") if isinstance(target, dict) else ""
        if not field and isinstance(target, dict):
            field = SELECTOR_TO_FIELD.get(str(target.get("selector") or ""), "")
            if field:
                target["field"] = field
        if field not in FIELD_SCHEMA:
            return None, "不支持的字段：" + str(field)
        config = FIELD_SCHEMA[field]
        value = action.get("value")
        if "options" in config and value not in config["options"]:
            return None, config["label"] + " 的字段值不在可选范围内：" + str(value)
        if config["kind"] == "checkbox" and not isinstance(value, bool):
            return None, config["label"] + " 必须是 boolean"

    normalized_action = {
        "thought": str(action.get("thought") or ""),
        "type": action_type,
        "target": target,
        "value": action.get("value"),
        "reason": str(action.get("reason") or ""),
        "done": bool(action.get("done")),
    }
    return normalized_action, None


def validate_universal_plan(plan: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(plan, dict):
        return None, "Qwen plan 不是 JSON object"

    patient = plan.get("patient") if isinstance(plan.get("patient"), dict) else {}
    patient_id = (patient.get("patientId") or "").strip().upper()
    patient_name = (patient.get("name") or "").strip()
    if not patient_id and patient_name:
        patient_id = PATIENT_NAME_TO_ID.get(patient_name, "")
    if not patient_id and not patient_name:
        return None, "patientId 或 name 至少需要一个"
    if patient_id and not patient_id.startswith("P"):
        return None, "patientId 格式不正确：" + patient_id

    raw_updates = plan.get("updates")
    if not isinstance(raw_updates, dict):
        return None, "updates 必须是 JSON object"

    normalized_updates: dict[str, Any] = {}
    for field, value in raw_updates.items():
        if value is None or value == "":
            continue
        if field not in FIELD_SCHEMA:
            return None, "不支持的字段：" + str(field)
        config = FIELD_SCHEMA[field]
        if "options" in config and value not in config["options"]:
            return None, config["label"] + " 的字段值不在可选范围内：" + str(value)
        if config["kind"] == "checkbox" and not isinstance(value, bool):
            return None, config["label"] + " 必须是 boolean"
        normalized_updates[field] = value

    if not normalized_updates:
        return None, "updates 中至少需要一个非 null 字段"

    validated = {
        "patient": {"patientId": patient_id, "name": patient_name},
        "updates": {field: normalized_updates.get(field) for field in FIELD_SCHEMA},
        "save": bool(plan.get("save")),
        "intent": "edit_patient",
        "confidence": plan.get("confidence", 0),
    }
    return validated, None


async def first_existing_locator(page: Any, selectors: list[str]) -> Any | None:
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count() > 0:
            return locator.first
    return None


async def field_locator(page: Any, config: dict[str, Any]) -> Any | None:
    locator = await first_existing_locator(page, config["selectors"])
    if locator:
        return locator
    by_label = page.get_by_label(config["label"], exact=True)
    if await by_label.count() > 0:
        return by_label.first
    return None


async def select_patient(page: Any, patient: dict[str, str], steps: list[str]) -> None:
    patient_id = patient.get("patientId") or ""
    patient_name = patient.get("name") or ""
    if not patient_id and patient_name:
        patient_id = PATIENT_NAME_TO_ID.get(patient_name, "")

    locator = await first_existing_locator(page, ["#patientSelect", '[data-testid="patient-select"]', 'select[name="patientSelect"]'])
    if not locator:
        raise ValueError("未找到就诊人选择控件")

    if patient_id:
        await locator.select_option(patient_id)
        steps.append("已选择就诊人 " + patient_id + ((" " + patient_name) if patient_name else ""))
        return

    selected_id = await page.evaluate(
        """(name) => {
            const select = document.querySelector('#patientSelect,[data-testid="patient-select"],select[name="patientSelect"]');
            if (!select) return '';
            const option = Array.from(select.options).find((item) => item.textContent.includes(name));
            if (!option) return '';
            select.value = option.value;
            select.dispatchEvent(new Event('change', { bubbles: true }));
            return option.value;
        }""",
        patient_name,
    )
    if not selected_id:
        raise ValueError("无法根据姓名找到就诊人：" + patient_name)
    patient["patientId"] = selected_id
    steps.append("已选择就诊人 " + selected_id + " " + patient_name)


async def apply_field_update(page: Any, field: str, value: Any, steps: list[str]) -> None:
    config = FIELD_SCHEMA[field]
    label = config["label"]
    kind = config["kind"]

    if kind == "radio":
        locator = await first_existing_locator(page, [f'input[name="visitType"][value="{value}"]', f'[aria-label="就诊类型 {value}"]'])
        if not locator:
            raise ValueError("未找到单选字段：" + label)
        await locator.check()
    elif kind == "checkbox":
        locator = await field_locator(page, config)
        if not locator:
            raise ValueError("未找到复选字段：" + label)
        await locator.set_checked(bool(value))
    else:
        locator = await field_locator(page, config)
        if not locator:
            raise ValueError("未找到字段：" + label)
        if kind == "select":
            await locator.select_option(str(value))
        else:
            await locator.fill(str(value))

    display_value = "是" if value is True else "否" if value is False else str(value)
    steps.append("已修改" + label + "为 " + display_value)


async def execute_plan_with_playwright(plan: dict[str, Any], target_url: str) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"ok": False, "mode": "universal-form-agent", "error": "Playwright 未安装，请运行 pip install playwright 并执行 playwright install chromium。"}

    steps = ["已解析任务"]
    browser = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False)
            page = await browser.new_page()
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            steps.append("已打开页面")

            await select_patient(page, plan["patient"], steps)
            for field, value in plan["updates"].items():
                if value is not None:
                    await apply_field_update(page, field, value, steps)

            if plan["save"]:
                locator = await first_existing_locator(page, ["#saveButton", '[data-testid="save-button"]', 'button[name="saveButton"]'])
                if not locator:
                    locator = page.get_by_role("button", name="保存修改")
                await locator.click()
                steps.append("已点击保存")
                await page.wait_for_timeout(300)

            preview_locator = await first_existing_locator(page, ["#jsonPreview", '[data-testid="json-preview"]'])
            preview = await preview_locator.inner_text(timeout=5000) if preview_locator else ""
            return {
                "ok": True,
                "mode": "universal-form-agent",
                "summary": "任务执行完成",
                "plan": plan,
                "steps": steps,
                "preview": preview,
            }
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        if "Executable doesn't exist" in message or "browser" in message.lower():
            message = "浏览器未安装或无法启动，请运行 playwright install chromium。原始错误：" + message
        return {"ok": False, "mode": "universal-form-agent", "error": message, "debug": {"plan": plan}}
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass


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
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        logs: list[str] = []

        def read_worker_output() -> None:
            if not process.stdout:
                return
            for line in process.stdout:
                logs.append(line)
                print_worker_log("[browser-use-worker] ", line)

        reader = threading.Thread(target=read_worker_output, daemon=True)
        reader.start()
        started_at = time.monotonic()
        try:
            while process.poll() is None:
                if time.monotonic() - started_at > timeout_seconds:
                    raise subprocess.TimeoutExpired(process.args, timeout_seconds)
                time.sleep(0.2)
        except subprocess.TimeoutExpired:
            process.kill()
            reader.join(timeout=3)
            return {
                "ok": False,
                "error": "Browser Use Agent 执行超时，可能卡在 Browser Use + ChatOpenAI/Qwen 层",
                "debugLog": sanitize_log("".join(logs)),
            }

        reader.join(timeout=3)
        debug_log = sanitize_log("".join(logs))
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


@app.post("/api/agent/run", response_model=None)
async def run_agent(payload: AgentRunRequest):
    command = payload.command.strip()
    if not command:
        return utf8_json({"ok": False, "error": "command 不能为空"}, 400)

    target_url = normalize_target_url(payload.targetUrl)
    if target_url != ALLOWED_TARGET_URL:
        return utf8_json({"ok": False, "error": "targetUrl 不被允许"}, 400)

    try:
        print_runtime_config()
        result = await asyncio.to_thread(run_browser_use_agent_subprocess, command, target_url, 180)
        status_code = 200 if result.get("ok") else 504 if "超时" in result.get("error", "") else 500
        return utf8_json(result, status_code)
    except RuntimeError as exc:
        return utf8_json({"ok": False, "error": str(exc)}, 400)
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        if "playwright" in message.lower() or "browser" in message.lower():
            message = "浏览器未安装或无法启动，请先运行 playwright install chromium。原始错误：" + message
        return utf8_json({"ok": False, "error": "Agent 执行失败：" + message}, 500)


def build_universal_plan_response(payload: AgentRunRequest) -> JSONResponse:
    try:
        command = payload.command.strip()
        if not command:
            return utf8_json({"ok": False, "mode": "universal-form-agent", "error": "command 不能为空"}, 400)

        target_url = normalize_target_url(payload.targetUrl)
        if target_url != ALLOWED_TARGET_URL:
            return utf8_json({"ok": False, "mode": "universal-form-agent", "error": "targetUrl 不被允许"}, 400)

        plan, raw_response, parse_error, llm_info = call_qwen_for_plan(command)
        if not llm_info.get("llmUsed"):
            return utf8_json(
                {
                    "ok": False,
                    "mode": "universal-form-agent",
                    "llmUsed": False,
                    "provider": "qwen",
                    "model": llm_info.get("model"),
                    "error": "Universal Form Agent 必须调用 LLM，但本次没有完成 LLM 调用",
                    "debug": {"reason": parse_error},
                },
                200,
            )

        if parse_error:
            return utf8_json(
                {
                    "ok": False,
                    "mode": "universal-form-agent",
                    "llmUsed": True,
                    "provider": "qwen",
                    "model": llm_info.get("model"),
                    "usage": llm_info.get("usage"),
                    "error": parse_error,
                    "rawResponse": raw_response,
                    "debug": {"rawResponse": raw_response},
                },
                200,
            )

        validated_plan, validation_error = validate_universal_plan(plan or {})
        if validation_error:
            return utf8_json(
                {
                    "ok": False,
                    "mode": "universal-form-agent",
                    "llmUsed": True,
                    "provider": "qwen",
                    "model": llm_info.get("model"),
                    "usage": llm_info.get("usage"),
                    "error": validation_error,
                    "debug": {"plan": plan, "rawResponse": raw_response},
                },
                200,
            )

        return utf8_json(
            {
                "ok": True,
                "mode": "universal-form-agent",
                "summary": "Qwen 已完成任务解析，请在当前页面执行 plan。",
                "llmUsed": True,
                "provider": "qwen",
                "model": llm_info.get("model"),
                "usage": llm_info.get("usage") or {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "plan": validated_plan,
                "rawResponse": raw_response,
            },
            200,
        )
    except Exception as exc:
        return utf8_json(
            {
                "ok": False,
                "mode": "universal-form-agent",
                "error": "Universal Form Agent 解析失败：" + (str(exc) or exc.__class__.__name__),
            },
            200,
        )


@app.post("/api/universal-agent/plan", response_model=None)
async def plan_universal_agent(payload: AgentRunRequest):
    return build_universal_plan_response(payload)


@app.post("/api/universal-agent/next-action", response_model=None)
async def next_universal_agent_action(payload: UniversalNextActionRequest):
    try:
        command = payload.command.strip()
        if not command:
            return utf8_json({"ok": False, "mode": "universal-observe-act-agent", "error": "command 不能为空"}, 400)
        if not isinstance(payload.pageState, dict) or not payload.pageState:
            return utf8_json({"ok": False, "mode": "universal-observe-act-agent", "error": "pageState 不能为空"}, 400)

        action, raw_response, parse_error, llm_info = call_qwen_for_next_action(payload)
        if not llm_info.get("llmUsed"):
            return utf8_json(
                {
                    "ok": False,
                    "mode": "universal-observe-act-agent",
                    "llmUsed": False,
                    "provider": "qwen",
                    "model": llm_info.get("model"),
                    "error": "Universal Observe-Act Agent 必须调用 LLM，但本次没有完成 LLM 调用",
                    "debug": {"reason": parse_error},
                },
                200,
            )

        if parse_error:
            return utf8_json(
                {
                    "ok": False,
                    "mode": "universal-observe-act-agent",
                    "llmUsed": True,
                    "provider": "qwen",
                    "model": llm_info.get("model"),
                    "usage": llm_info.get("usage"),
                    "error": parse_error,
                    "rawResponse": raw_response,
                    "debug": {"rawResponse": raw_response},
                },
                200,
            )

        validated_action, validation_error = validate_universal_action(action or {})
        if validation_error:
            return utf8_json(
                {
                    "ok": False,
                    "mode": "universal-observe-act-agent",
                    "llmUsed": True,
                    "provider": "qwen",
                    "model": llm_info.get("model"),
                    "usage": llm_info.get("usage"),
                    "error": validation_error,
                    "debug": {"action": action, "rawResponse": raw_response},
                },
                200,
            )

        return utf8_json(
            {
                "ok": True,
                "mode": "universal-observe-act-agent",
                "llmUsed": True,
                "provider": "qwen",
                "model": llm_info.get("model"),
                "usage": llm_info.get("usage") or {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "action": validated_action,
                "rawResponse": raw_response,
            },
            200,
        )
    except Exception as exc:
        return utf8_json(
            {
                "ok": False,
                "mode": "universal-observe-act-agent",
                "error": "Universal Observe-Act Agent 决策失败：" + (str(exc) or exc.__class__.__name__),
            },
            200,
        )


@app.post("/api/universal-agent/run", response_model=None)
async def run_universal_agent(payload: AgentRunRequest):
    return build_universal_plan_response(payload)


def parse_quick_agent_command(command: str) -> dict[str, Any]:
    patient_id = ""
    for candidate in ["P001", "P002", "P003", "P004", "P005"]:
      if candidate in command.upper():
          patient_id = candidate
          break

    updates: dict[str, str] = {}

    phone_match = re_search(r"(?:手机号|手机|联系电话).*?(?:修改为|改为|改成|设置为)\s*([0-9]{1,20})", command)
    if phone_match:
        updates["phone"] = phone_match

    department_options = ["呼吸内科", "消化内科", "心血管内科", "神经内科", "骨科", "皮肤科", "儿科", "眼科", "耳鼻喉科", "急诊科"]
    for option in department_options:
        if option in command and ("科室" in command or "就诊科室" in command):
            updates["department"] = option
            break

    for option in ["初诊", "复诊", "急诊"]:
        if option in command and "就诊类型" in command:
            updates["visitType"] = option
            break

    symptoms = re_search(r"(?:主诉/症状描述|主诉|症状描述|症状).*?(?:修改为|改为|改成|设置为)\s*(.+?)(?:，然后|,然后|然后点击保存|点击保存|。|$)", command)
    if symptoms:
        updates["symptoms"] = symptoms.strip(" ，,。")

    return {
        "patientId": patient_id,
        "updates": updates,
        "shouldSave": any(keyword in command for keyword in ["保存", "点击保存", "然后保存", "提交"]),
    }


def re_search(pattern: str, text: str) -> str:
    import re

    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


async def select_by_selector_or_testid(page: Any, css_selector: str, test_id: str) -> Any:
    locator = page.locator(css_selector)
    if await locator.count() > 0:
        return locator.first
    return page.get_by_test_id(test_id)


async def run_quick_agent(command: str, target_url: str) -> dict[str, Any]:
    parsed = parse_quick_agent_command(command)
    if not parsed["patientId"]:
        return {"ok": False, "mode": "playwright-smoke-test", "error": "没有识别到支持的就诊人，请输入 P001 到 P005。"}
    if not parsed["updates"]:
        return {"ok": False, "mode": "playwright-smoke-test", "error": "没有识别到要修改的字段。"}

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"ok": False, "mode": "playwright-smoke-test", "error": "Playwright 未安装，请运行 pip install playwright 并执行 playwright install chromium。"}

    steps = []
    browser = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False)
            page = await browser.new_page()
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            steps.append("已打开页面")

            await page.locator("#patientSelect").select_option(parsed["patientId"])
            steps.append("已选择就诊人 " + parsed["patientId"])

            updates = parsed["updates"]
            if "phone" in updates:
                await page.locator("#phoneInput").fill(updates["phone"])
                steps.append("已修改手机号为 " + updates["phone"])

            if "department" in updates:
                await page.locator("#departmentSelect").select_option(updates["department"])
                steps.append("已修改就诊科室为 " + updates["department"])

            if "visitType" in updates:
                await page.locator('input[name="visitType"][value="' + updates["visitType"] + '"]').check()
                steps.append("已修改就诊类型为 " + updates["visitType"])

            if "symptoms" in updates:
                await page.locator("#symptomsTextarea").fill(updates["symptoms"])
                steps.append("已修改主诉/症状描述为 " + updates["symptoms"])

            if parsed["shouldSave"]:
                await page.locator("#saveButton").click()
                steps.append("已点击保存")
                await page.wait_for_timeout(300)

            preview = await page.locator("#jsonPreview").inner_text(timeout=5000)
            return {
                "ok": True,
                "mode": "playwright-smoke-test",
                "summary": "任务执行完成",
                "steps": steps,
                "preview": preview,
            }
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        if "Executable doesn't exist" in message or "browser" in message.lower():
            message = "浏览器未安装或无法启动，请运行 playwright install chromium。原始错误：" + message
        return {"ok": False, "mode": "playwright-smoke-test", "error": message}
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass


@app.post("/api/quick-agent/run", response_model=None)
async def run_quick_agent_api(payload: AgentRunRequest):
    command = payload.command.strip()
    if not command:
        return utf8_json({"ok": False, "mode": "playwright-smoke-test", "error": "command 不能为空"}, 400)

    target_url = normalize_target_url(payload.targetUrl)
    if target_url != ALLOWED_TARGET_URL:
        return utf8_json({"ok": False, "mode": "playwright-smoke-test", "error": "targetUrl 不被允许"}, 400)

    result = await run_quick_agent(command, target_url)
    return utf8_json(result, 200 if result.get("ok") else 500)
