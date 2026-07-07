#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
各 batch 共 5 个轮次（第一轮…第五轮，按 prompts 根下活动 batch 键顺序切换）；
全部 batch 第一轮结束后等 5s（与原先一致），其余轮次之间无额外等待。
第 2～5 轮：打开该 batch 并等待后、**输入本轮提示词之前**全屏截图，将绝对路径写入 ``output.json`` 对应 **上一轮** 条目的「截图（产物/运行结果/对话）」字段。
仅用 ``111.py`` 的 ``create_workspace_dir``、``open_trae``。
"""
import importlib.util
import json
import re
import time
from pathlib import Path

import pyautogui

pyautogui.FAILSAFE = False

import locate_trae_ui as loc

_SCRIPT_DIR = Path(__file__).resolve().parent
PROMPTS_JSON = _SCRIPT_DIR / "prompts.json"
OUTPUT_JSON = _SCRIPT_DIR / "output.json"
SCREENSHOT_DIR = _SCRIPT_DIR / "batch_two_screenshots"
SHOT_FIELD = "截图（产物/运行结果/对话）"

# 写死：各 batch 工作区父目录 …/0512/batch1、batch2 …
BATCH_WORK_ROOT = Path("/Users/lxy/Documents/wkspsTreacn/test-DF/packages/0601")

_spec = importlib.util.spec_from_file_location("mod111", _SCRIPT_DIR / "111.py")
_mod111 = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod111)
create_workspace_dir = _mod111.create_workspace_dir
open_trae = _mod111.open_trae

# 打开工作区后再等 10s 再输入提示词（111 内 open 后另有 sleep(3)）
WAIT_AFTER_OPEN_EXTRA_SEC = 10.0
WAIT_AFTER_BATCH2_ROUND1_SEC = 420.0

ROUND_LABELS = ["第一轮", "第二轮", "第三轮", "第四轮", "第五轮"]


def _natural_batch_keys(pdata):
    keys = [k for k, v in pdata.items() if isinstance(v, list) and v]

    def sort_key(name):
        m = re.match(r"^(.*?)(\d+)$", str(name))
        if m:
            return (m.group(1), int(m.group(2)))
        return (str(name), 0)

    return sorted(keys, key=sort_key)


def _round_user_prompt(cases, round_name):
    for c in cases:
        if (c.get("轮次") or "").strip() == round_name:
            return (c.get("User Prompt") or "").strip()
    return ""


def _screenshot_save(batch_id, completed_round_label):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    safe = completed_round_label.replace("/", "_")
    path = SCREENSHOT_DIR / f"{batch_id}_{safe}.png"
    pyautogui.screenshot(str(path))
    return path.resolve()


def _patch_output_screenshot(out_data, batch_id, completed_round_label, png_path):
    for row in out_data.get(batch_id, []):
        if (row.get("轮次") or "").strip() == completed_round_label.strip():
            row[SHOT_FIELD] = str(png_path)
            return True
    return False


def _write_output_json(out_data):
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

def _copy_to_clipboard(text):
    data = text.encode("utf-8")
    p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    p.communicate(data)
    if p.returncode != 0:
        raise RuntimeError("pbcopy 失败，无法写入剪贴板")


def _send_prompt_by_click(app, prompt):
    app.activate()
    time.sleep(1.0)
    pyautogui.click(INPUT_X, INPUT_Y)
    time.sleep(5.0)
    pyautogui.click(INPUT_X, INPUT_Y)
    time.sleep(1.0)
    _copy_to_clipboard(prompt)
    keyboard.hotkey("command", "a")
    time.sleep(1.0)
    keyboard.hotkey("command", "v")
    time.sleep(1.0)
    pyautogui.press("enter")
    time.sleep(2.0)

def _send_round(
    batch_id,
    workspace,
    round_label,
    prompt,
    out_data,
    screenshot_prev_round=None,
):
    if not prompt:
        raise SystemExit(f"{batch_id} 缺少{round_label} User Prompt")
    print(f"[{batch_id}] 打开工作区: {workspace}", flush=True)
    app = open_trae(workspace)
    loc.app = app
    time.sleep(WAIT_AFTER_OPEN_EXTRA_SEC)
    if screenshot_prev_round:
        shot_path = _screenshot_save(batch_id, screenshot_prev_round)
        if not _patch_output_screenshot(out_data, batch_id, screenshot_prev_round, shot_path):
            raise SystemExit(
                f"output.json 中未找到 {batch_id!r} 轮次 {screenshot_prev_round!r}，无法写入截图路径"
            )
        _write_output_json(out_data)
        print(
            f"[{batch_id}] 已截图（上一轮 {screenshot_prev_round}）→ {shot_path}，已写入 output.json",
            flush=True,
        )
    print(f"[{batch_id}] 发送{round_label}…", flush=True)
    loc.input_prompt(prompt)
    time.sleep(1.0)
    pyautogui.press("enter", 2)
    time.sleep(0.2)
    pyautogui.press("enter", 2)
    print(f"[{batch_id}] 已按回车发送", flush=True)
    time.sleep(60.0)


def main():
    with open(PROMPTS_JSON, "r", encoding="utf-8") as f:
        pdata = json.load(f)
    with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
        out_data = json.load(f)

    batch_keys = _natural_batch_keys(pdata)
    if not batch_keys:
        raise SystemExit("prompts.json 中没有非空的 batch 用例列表")

    # workspaces = {
    #     bk: create_workspace_dir(bk, base_work_dir=None) for bk in batch_keys
    # }

    root = BATCH_WORK_ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspaces = {}
    for bk in batch_keys:
        p = (root / bk).resolve()
        p.mkdir(parents=True, exist_ok=True)
        workspaces[bk] = p

    for ri, round_label in enumerate(ROUND_LABELS):
        for bk in batch_keys:
            cases = pdata.get(bk) or []
            pr = _round_user_prompt(cases, round_label)
            if ri == 0 and not pr and cases:
                pr = (cases[0].get("User Prompt") or "").strip()
            prev = ROUND_LABELS[ri - 1] if ri > 0 else None
            _send_round(
                bk,
                workspaces[bk],
                round_label,
                pr,
                out_data,
                screenshot_prev_round=prev,
            )
        if ri == 0:
            print(
                f"[全部 batch 第一轮结束] 等待 {WAIT_AFTER_BATCH2_ROUND1_SEC}s …",
                flush=True,
            )
            time.sleep(WAIT_AFTER_BATCH2_ROUND1_SEC)

    print("完成。", flush=True)


if __name__ == "__main__":
    main()
