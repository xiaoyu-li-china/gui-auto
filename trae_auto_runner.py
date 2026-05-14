#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
# atomacos / PyObjC 需要 Python 3.9+；若本机无 python3.11，可改用 python3.10 等并相应改 shebang。
import os
import time
import json
import subprocess
import csv
import io
import shutil
import re
import shlex
from datetime import datetime
from pathlib import Path
from PIL import ImageGrab
import atomacos
from atomacos import keyboard, mouse

from savefile import save_session_and_log_to_output_json

_SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_JSON = _SCRIPT_DIR / "output.json"
PROMPTS_JSON = _SCRIPT_DIR / "prompts.json"
OUTPUT_JSON_FIXED = _SCRIPT_DIR / "output.json"
BATCH_KEY_DEFAULT = "batch1"  # 与 prompts.json / output.json 中键一致；仍支持别名 batch001
MAX_PROMPT_ROUNDS = 5
WAIT_AFTER_OPEN_FOR_INDEX = 10  # open 工作区后等待 Trae 就绪（秒）
# 多 batch 交错：所有 batch 发完「第一轮」后统一等待（秒）
WAIT_AFTER_ALL_BATCHES_ROUND1_SEC = 10
# 第一轮快速发送后、切换 batch 前短停（秒）
ROUND1_QUICK_SEND_TAIL_SEC = 2.0
# 截图根目录（与需求命名 batch/轮次 一致）
SCREENSHOT_INTERLEAVED_ROOT = _SCRIPT_DIR / "trae_cn_test_screnshots"
# 同一 run 内再次 open 同一/另一工作区时的等待（秒），短于首次 WAIT_AFTER_OPEN_FOLDER
WAIT_AFTER_OPEN_FOLDER_REOPEN = 3
# 交错多 batch：从第 2 个 batch 起使用 open -n 新开 Trae（否则已运行时只会聚焦、不打开 batch2 目录）
# 终端切勿写成 open [-n]：zsh 会把 [ 当 glob，报「no matches found: [-n]」；应写成两个参数：open -n ...
INTERLEAVED_USE_NEW_TRAE_INSTANCE_FROM_BATCH_INDEX = 1  # 0 起：>=1 即 batch2 起用 -n
# `open -n` 启动第二个 Trae 后额外等待（秒），需等窗口与工作区就绪
WAIT_AFTER_NEW_TRAE_INSTANCE_SEC = 14
# batch1 第一轮发完 → 回桌面 → 再 open batch2 之间多等几秒（桌面动画 / 释放焦点）
WAIT_AFTER_DESKTOP_BEFORE_OPEN_NEXT_BATCH_SEC = 3.5
# 用 Bundle ID 调用 open（无路径仅启动时等场景）；带「文件夹作工作区」时见下条
OPEN_TRAE_WITH_BUNDLE_ID = True
# 打开「文件夹作为工作区」时是否与 111.py 一致：优先 ``open -a "Trae CN" <路径>``。
# 许多机器上 ``open -b cn.trae.app <路径>`` 会返回成功却未挂上目录，导致 runner「打不开」而 111.py 正常。
OPEN_TRAE_WORKSPACE_USE_APP_NAME_FIRST = True
# 当上一项为 False 且主方式为 ``-b`` 时，``-b`` 连续失败后再尝试 ``-a``（与旧版回退一致）
OPEN_TRAE_FALLBACK_APP_NAME_ON_BUNDLE_FAIL = True
# 当 ``OPEN_TRAE_WORKSPACE_USE_APP_NAME_FIRST`` 为 True 且 ``-a`` 仍失败时，再尝试 ``open -b <bundle> <路径>``
OPEN_TRAE_FALLBACK_BUNDLE_AFTER_APP_NAME_FAIL = True
# 新开 Trae 时：在首次 open -n 后再 ``open -b`` 一次（**不带** -n），促使当前前台实例挂上工作区（默认关，避免误开第三窗口）
OPEN_TRAE_NEW_INSTANCE_ATTACH_SECOND_OPEN = False
OPEN_TRAE_NEW_INSTANCE_SECOND_GAP_SEC = 2.0
# 交错 run 工作区根：False=固定 BASE_WORK_DIR/0513（即 …/packages/0513，batch1|batch2 子目录在此下）
# True=每次 gui_auto_interleaved_YYYYMMDD_HHMMSS（历史隔离；日志里旧路径常会「目录不存在」）
INTERLEAVED_USE_TIMESTAMPED_RUN_DIR = False
INTERLEAVED_STABLE_RUN_DIR_NAME = "0513"
INTERLEAVED_LAST_PATHS_FILE = _SCRIPT_DIR / "last_interleaved_workspaces.txt"
# 顺序多 batch（--interleaved-sequential）时：是否在两个 batch 之间执行 pkill Trae CN（更干净但更慢）
INTERLEAVED_QUIT_TRAE_BETWEEN_BATCHES = False
TRAE_BUNDLE_ID = "cn.trae.app"  # 你的 Trae CN Bundle ID
# macOS ``open -a`` 使用的应用名（须与「应用程序」里显示名一致，与 111.py 相同）
TRAE_CN_APP_NAME = "Trae CN"
# 使用系统自带 ``open``，避免 PATH 或 alias 影响（与终端手动执行一致）
OPEN_EXECUTABLE = "/usr/bin/open"
PROMPTS_FILE = _SCRIPT_DIR / "prompts.txt"  # CSV/引号字段；见 load_prompts
BASE_WORK_DIR = Path("/Users/oce/Documents/TreaAi/test_dogfooding/packages")  # 工作根目录
LOCAL_SAVE_DIR = _SCRIPT_DIR / "output"  # 最终结果保存目录

# UI 元素定位（name 中 | 表示“任一子串匹配即可”，不区分大小写）
# 参考 Trae 界面：左下角聊天框占位符多为「您正在与 SOLO Coder 聊天...」
INPUT_BOX = {"role": "AXTextArea", "name": "solo coder|您正在与|聊天|输入消息|/plan"}
# 绿色上箭头等图标按钮常无 AXTitle，仅靠 name 找不到；会再用底部启发式 + 比例点击兜底。
SEND_BUTTON = {
    "role": "AXButton",
    "name": "发送|send|提交|submit|送出|上箭头|arrow|↑|发送消息",
}
OUTPUT_AREA = {"role": "AXStaticText", "name": ""}  # name 可为空，取第一个输出区域

# 找不到 AXButton 时，在整窗比例位置点击（中间栏底部偏右，接近绿色「发送」箭头）
SEND_CLICK_FALLBACK = True
SEND_CLICK_X_FRAC = 0.54
SEND_CLICK_Y_FRAC = 0.90

# 等待时间（秒）
WAIT_AFTER_LAUNCH = 3  # 仅启动客户端、未打开文件夹时
WAIT_AFTER_OPEN_FOLDER = 8  # open 指定工作区后等待索引/界面就绪（可按机器调整）
WAIT_AFTER_SEND_FALLBACK = 120  # 若「输出稳定」检测超时，最多再等这么多秒（兜底）
WAIT_BETWEEN_ROUNDS = 2  # 同一会话内三轮之间的间隔
WAIT_BETWEEN_BATCHES = 3  # 关闭旧客户端到开启新客户端的间隔

# 输出完成判定：轮询聊天区全文快照，连续无变化即视为本轮生成结束
OUTPUT_POLL_INTERVAL = 0.6
OUTPUT_STABLE_SECONDS = 3.0  # 无新变化持续此时间则认为输出完毕（流式会不断刷新）
OUTPUT_MAX_WAIT = 600  # 单轮最长等待
OUTPUT_MIN_WAIT_AFTER_SEND = 2.0  # 发送后至少等这么久再允许「稳定即结束」（避免误触发）
OUTPUT_MIN_TEXT_GROWTH = 30  # 相对发送前快照，至少多出这么多字才认为开始有回复（太小易受 UI 噪声干扰）

# _wait_for_output_complete 内每隔多少秒打一行进度（0=关闭）。避免误以为卡住，实则在等模型输出。
OUTPUT_WAIT_HEARTBEAT_SEC = 20.0

# 顺序多 batch：第一个 batch 冷启动后、发第一轮前再 stabilize（传给 _stabilize 的 timeout 上限，秒；≤0 关闭）。
SEQUENTIAL_STABILIZE_SEC_FIRST_BATCH = 12.0

WAIT_AFTER_FOCUS_CLICK = 0.25  # 点击聊天区域、粘贴后的稍停
WAIT_AFTER_ACTIVATE_BEFORE_PASTE = 0.55

# 粘贴前在窗口内点一下，把焦点锁到中间栏 SOLO Coder 输入区（相对整窗 0~1）。
# 三栏布局可参考 x≈0.38~0.45（避开左侧任务栏与右侧编辑器），y≈0.88~0.92（底部输入条）。
PASTE_CLICK_BEFORE = True
CHAT_CLICK_X_FRAC = 0.40
CHAT_CLICK_Y_FRAC = 0.90

# 发送键鼠前必须确认 Trae 为前台（否则会贴到 Cursor/终端却显示「已保存」）。
ENSURE_TRAE_FRONTMOST_TIMEOUT = 20.0
# open 工作区后额外给 Trae 首启/索引的「抢焦点」时间（秒），与 _stabilize_trae_after_open_workspace 配合
TRAE_FRONTMOST_AFTER_OPEN_TIMEOUT = 28.0

# True：第二路 Trae（open -n）及乒乓里切换 batch 工作区后，不再做 _stabilize / _ensure_trae_frontmost 长轮询，
# 仅短 ``activate`` + 睡眠；首路 batch1 仍保留原「等索引 + 确认前台」。粘贴与 send_prompt 逻辑不变。
TRAE_LIGHT_OPEN_SKIP_LONG_FOCUS = True
TRAE_LIGHT_OPEN_ACTIVATE_SLEEP_SEC = 0.4

# ``activate`` 后若仍被 PyCharm/终端抢前台，在 Trae 首个有标题主窗口内点一下（相对窗口 0~1），
# 等价于人工点一下窗口内容区夺焦点；与 CHAT_CLICK_* 独立，默认点在中间偏上、避开底栏发送区。
CLICK_TRAE_WINDOW_TO_RESTORE_FOCUS = True
RESTORE_FOCUS_CLICK_X_FRAC = 0.48
RESTORE_FOCUS_CLICK_Y_FRAC = 0.40

# 粘贴后是否用无障碍读取文本并校验已贴上（读不到 AXValue 时可改为 False）。
VERIFY_PROMPT_IN_CHAT_AFTER_PASTE = True
# 切换工作区 / 多 batch 乒乓后，聊天框 AX 常短暂不可读，send_prompt 可跳过粘贴后校验（仍执行粘贴与发送）。
SEND_PROMPT_SKIP_VERIFY_AFTER_WORKSPACE_SWITCH = True

# True：输入提示词走「打开目录已由 open_trae 完成 → activate → 按 CHAT_CLICK_* 点输入区获焦 → Cmd+A/V」，
# 不做 ``_ensure_trae_frontmost`` 超时阻塞、不做双轮回试；默认不做粘贴后 AX 校验（显式 ``verify_prompt_in_chat=True`` 仍可校验）。
# False：恢复原先「三重前台确认 + 最多两轮粘贴 + 默认按 VERIFY_PROMPT_IN_CHAT_AFTER_PASTE 校验」。
TRAE_SIMPLE_OPEN_CLICK_PASTE = True

# 粘贴后校验：长提示只取前 N 字做子串；≤40 字（如测试「123」）用整段匹配。
VERIFY_PROMPT_MAX_PROBE_LEN = 120

# 在 trigger_send 尝试按钮/快捷键/比例点之后，再按一次 Return（部分 Trae 仅靠 Enter 才提交输入框）。
PRESS_ENTER_TO_SEND_AFTER_TRIGGER = True

# 在粘贴前额外按快捷键（pyautogui.hotkey 参数元组列表），用于把焦点切到 AI。
FOCUS_AI_INPUT_HOTKEYS = []  # 例: [("command", "l")]

BATCH_SIZE = 3  # 每批在 Trae 输入框内连续发送的轮数（三轮提示词）
TOTAL_ROUNDS = 3  # 本脚本总共执行的轮次数（与 prompts 前 N 行对应）

# 每批结束后是否退出 Trae CN（pkill）。调试或希望保持客户端开启时请设为 False。
CLOSE_TRAE_AFTER_EACH_BATCH = False


def _running_bundle_pids(bundle_id=None):
    """
    当前系统中指定 Bundle ID 的进程 PID 列表（升序、去重）。
    用于多开 Trae 时为每个 batch 绑定 ``getAppRefByPid``；亦用于前台判定。
    """
    bid = bundle_id or TRAE_BUNDLE_ID
    try:
        from AppKit import NSRunningApplication

        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bid)
        if not apps:
            return []
        return sorted({int(a.processIdentifier()) for a in apps})
    except Exception:
        return []


# =====================================================

def load_prompts(file_path):
    """支持 CSV 引号字段、尾随逗号、跨行单元格（与当前 prompts.txt 格式一致）。"""
    path = Path(file_path)
    raw = path.read_text(encoding="utf-8")
    reader = csv.reader(io.StringIO(raw))
    prompts = []
    for row in reader:
        for cell in row:
            c = (cell or "").strip()
            if c:
                prompts.append(c)
                break
    if len(prompts) < TOTAL_ROUNDS:
        raise ValueError(f"提示词文件只解析出 {len(prompts)} 条，需要 {TOTAL_ROUNDS} 条")
    return prompts[:TOTAL_ROUNDS]


def _a11y_text_bucket(elem):
    """合并常用可访问性文案，用于占位符/标题匹配。"""
    chunks = []
    for key in (
            "AXTitle",
            "AXValue",
            "AXPlaceholderValue",
            "AXDescription",
            "AXHelp",
            "AXRoleDescription",
    ):
        try:
            if key not in elem.ax_attributes:
                continue
            v = getattr(elem, key, None)
            if v is not None and str(v).strip():
                chunks.append(str(v))
        except Exception:
            pass
    return " ".join(chunks).lower()


def _name_criteria_match(criteria_name, elem):
    if not criteria_name or not str(criteria_name).strip():
        return True
    hay = _a11y_text_bucket(elem)
    parts = [p.strip().lower() for p in str(criteria_name).split("|") if p.strip()]
    return any(p in hay for p in parts)


def _refresh_trae_app(app=None):
    """Electron 客户端 UI 树会变，重新取 application 引用更稳。"""
    try:
        return atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
    except Exception:
        return app


def _foreground_app_is_trae_cn():
    """
    用 ``NSWorkspace.frontmostApplication`` 判断前台是否为 Trae CN。
    部分环境下 ``getFrontmostApp().bundle_id`` 与 ``TRAE_BUNDLE_ID`` 比对失败，但系统前台已是 Trae。
    """
    try:
        from AppKit import NSWorkspace

        fm = NSWorkspace.sharedWorkspace().frontmostApplication()
        if fm is None:
            return False
        bid = str(fm.bundleIdentifier() or "")
        if bid == TRAE_BUNDLE_ID:
            return True
        pid = int(fm.processIdentifier())
        return pid in set(_running_bundle_pids())
    except Exception:
        return False


def _click_trae_window_for_focus():
    """
    在 Trae 主窗口内点一下，帮助从其它应用夺回焦点（需 ``CLICK_TRAE_WINDOW_TO_RESTORE_FOCUS``）。
    """
    if not CLICK_TRAE_WINDOW_TO_RESTORE_FOCUS:
        return False
    try:
        app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
    except Exception:
        return False
    return _click_window_fraction(
        app, RESTORE_FOCUS_CLICK_X_FRAC, RESTORE_FOCUS_CLICK_Y_FRAC
    )


def _ensure_trae_frontmost(timeout=None):
    """
    确认当前前台为 Trae CN：``getFrontmostApp``、``NSWorkspace`` 与 Trae 进程 PID 三重校验；
    期间反复 ``activate``（含各 PID 实例）；可选间隔在窗口内点击，缓解仅 activate 无效的情况。
    """
    limit = float(timeout if timeout is not None else ENSURE_TRAE_FRONTMOST_TIMEOUT)
    deadline = time.time() + limit
    n = 0
    while time.time() < deadline:
        try:
            front = atomacos.getFrontmostApp()
            if getattr(front, "bundle_id", None) == TRAE_BUNDLE_ID:
                return True
        except (ValueError, Exception):
            pass
        if _foreground_app_is_trae_cn():
            return True
        try:
            atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID).activate()
        except Exception:
            pass
        for pid in reversed(_running_bundle_pids()):
            try:
                atomacos.getAppRefByPid(pid).activate()
            except Exception:
                pass
        n += 1
        if CLICK_TRAE_WINDOW_TO_RESTORE_FOCUS and n % 3 == 0:
            _click_trae_window_for_focus()
        time.sleep(0.35)
    return False


def _stabilize_trae_after_open_workspace(*, timeout=None):
    """
    ``open`` 打开工作区后：短 burst 多次 ``activate``，再延长前台检测。
    缓解 PyCharm/终端抢焦点、Trae 冷启动未就绪导致的 send_prompt 失败。
    """
    lim = float(timeout if timeout is not None else TRAE_FRONTMOST_AFTER_OPEN_TIMEOUT)
    for i in range(8):
        try:
            atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID).activate()
        except Exception:
            pass
        for pid in reversed(_running_bundle_pids()):
            try:
                atomacos.getAppRefByPid(pid).activate()
            except Exception:
                pass
        if CLICK_TRAE_WINDOW_TO_RESTORE_FOCUS and i in (2, 5):
            _click_trae_window_for_focus()
        time.sleep(0.45)
        if _foreground_app_is_trae_cn():
            return True
    return _ensure_trae_frontmost(timeout=lim)


def _activate_trae_short(app=None):
    """轻量聚焦：不做前台轮询，供第二实例 / 切换工作区后衔接粘贴。"""
    try:
        _refresh_trae_app(app).activate()
    except Exception:
        pass
    time.sleep(TRAE_LIGHT_OPEN_ACTIVATE_SLEEP_SEC)


def _click_window_fraction(app, fx, fy):
    """在第一个有标题的主窗口内按 (fx, fy) 比例点击（0~1）。"""
    app = _refresh_trae_app(app)
    for win in app.windows():
        try:
            if not (win.AXTitle or "").strip():
                continue
        except Exception:
            continue
        bbox = _window_bbox(win)
        if not bbox:
            continue
        x0, y0, x1, y1 = bbox
        cx = x0 + (x1 - x0) * fx
        cy = y0 + (y1 - y0) * fy
        try:
            app.activate()
            time.sleep(0.12)
            mouse.moveTo(cx, cy)
            time.sleep(0.06)
            mouse.click(cx, cy)
            time.sleep(WAIT_AFTER_FOCUS_CLICK)
        except Exception:
            return False
        return True
    return False


def _probe_for_verify(prompt):
    """校验用片段：短提示全文参与匹配，便于测试「123」等。"""
    s = (prompt or "").strip()
    if not s:
        return ""
    if len(s) <= 40:
        return s
    return s[:VERIFY_PROMPT_MAX_PROBE_LEN]


def _chat_input_reflects_prompt(app, prompt):
    """
    确认提示词是否已进入 Trae 内可编辑文本：当前系统焦点控件、find_chat_input、
    以及主窗口内靠下的多个 AXTextArea/AXTextField 逐一读 AXValue。
    完全读不到任何文本控件返回 None；读到但不匹配返回 False。
    """
    if not (prompt or "").strip():
        return True
    probe = _probe_for_verify(prompt)
    if not probe:
        return True
    app = _refresh_trae_app(app)

    def matches(cur):
        if cur is None:
            return False
        c = str(cur)
        if probe in c:
            return True
        return c.strip() == (prompt or "").strip()

    # A) 系统级 AXFocusedUIElement，且所属应用为 Trae
    try:
        sw = atomacos.NativeUIElement.systemwide()
        if "AXFocusedUIElement" in sw.ax_attributes:
            fe = sw.AXFocusedUIElement
            if fe is not None:
                try:
                    app_el = fe.getApplication()
                    if getattr(app_el, "bundle_id", None) == TRAE_BUNDLE_ID:
                        if matches(_safe_ax_value_str(fe)):
                            return True
                except Exception:
                    pass
    except Exception:
        pass

    # B) 原有占位符 + 最靠下兜底
    el = find_chat_input(app)
    if el is not None:
        if matches(_safe_ax_value_str(el)):
            return True

    # C) 所有文本框按纵向位置排序，取底部若干个比对（不依赖「找聊天框」）
    any_widget = False
    for win in app.windows():
        try:
            if not (win.AXTitle or "").strip():
                continue
        except Exception:
            continue
        scored = []
        for elem in _collect_by_role(win, "AXTextArea") + _collect_by_role(win, "AXTextField"):
            any_widget = True
            try:
                f = elem.AXFrame
                bottom = float(f.y + f.height)
            except Exception:
                bottom = 0.0
            scored.append((bottom, _safe_ax_value_str(elem)))
        scored.sort(key=lambda t: -t[0])
        for _, cur in scored[:15]:
            if matches(cur):
                return True
    if not any_widget:
        return None
    return False


def _safe_ax_children(elem):
    """Trae/Electron 部分节点未暴露 AXChildren，直接访问会 AttributeError。"""
    try:
        attrs = elem.ax_attributes
        if attrs and "AXChildren" in attrs:
            ch = elem.AXChildren
            if not ch:
                return []
            return list(ch)
    except Exception:
        pass
    return []


def _copy_to_clipboard(text):
    data = text.encode("utf-8")
    p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    p.communicate(data)
    if p.returncode != 0:
        raise RuntimeError("pbcopy 失败，无法写入剪贴板")


def _elem_center_point(elem):
    try:
        if "AXFrame" in elem.ax_attributes:
            f = elem.AXFrame
            return (float(f.x + f.width / 2), float(f.y + f.height / 2))
    except Exception:
        pass
    try:
        p = elem.AXPosition
        s = elem.AXSize
        return (float(p.x + s.width / 2), float(p.y + s.height / 2))
    except Exception as e:
        raise RuntimeError(f"无法计算元素中心坐标: {e}") from e


def _try_ax_focus(elem):
    try:
        if "AXFocused" in elem.ax_attributes:
            elem.AXFocused = True
            return True
    except Exception:
        pass
    return False


def _safe_ax_value_str(elem):
    try:
        if "AXValue" in elem.ax_attributes:
            v = elem.AXValue
            if v is not None:
                return str(v)
    except Exception:
        pass
    return ""


def _chat_ui_text_snapshot(app):
    """收集主窗口内可见文本控件的文案，用于判断回复是否仍在增长/已稳定。"""
    parts = []

    def walk(elem):
        try:
            role = elem.AXRole
            if role in ("AXStaticText", "AXTextArea", "AXTextField"):
                v = _safe_ax_value_str(elem)
                if v.strip():
                    parts.append(v)
            for c in _safe_ax_children(elem):
                walk(c)
        except Exception:
            pass

    for win in app.windows():
        try:
            if not (win.AXTitle or "").strip():
                continue
        except Exception:
            continue
        walk(win)
    return "\n".join(parts)


def _wait_for_output_complete(app, snapshot_before_send):
    """
    发送后轮询 UI 文本快照：流式输出会持续变化；连续 OUTPUT_STABLE_SECONDS 无变化且
    文本相对发送前增长足够，则认为本轮输出结束。
    """
    app = _refresh_trae_app(app)
    try:
        app.activate()
    except Exception:
        pass

    start = time.time()
    last_text = None
    last_change = start
    pre_len = len(snapshot_before_send or "")
    min_len_done = pre_len + OUTPUT_MIN_TEXT_GROWTH
    hb = float(OUTPUT_WAIT_HEARTBEAT_SEC or 0.0)
    next_hb = start + hb if hb > 0 else float("inf")

    while time.time() - start < OUTPUT_MAX_WAIT:
        app = _refresh_trae_app(app)
        text = _chat_ui_text_snapshot(app)
        now = time.time()
        if hb > 0 and now >= next_hb:
            print(
                f"[wait_output] 已等待 {now - start:.0f}s，快照长度={len(text)}，"
                f"需相对发送前至少再长 {OUTPUT_MIN_TEXT_GROWTH} 字才易判定为「有回复」",
                flush=True,
            )
            next_hb = now + hb
        if text != last_text:
            last_change = now
            last_text = text

        elapsed = now - start
        if elapsed >= OUTPUT_MIN_WAIT_AFTER_SEND:
            stable_for = now - last_change
            grew_enough = len(text) >= min_len_done
            # 极短回复：时间够长且相对发送前有增长、快照已稳定，也视为结束
            if (
                    not grew_enough
                    and elapsed >= 45
                    and len(text) > pre_len
                    and stable_for >= OUTPUT_STABLE_SECONDS
            ):
                grew_enough = True
            if grew_enough and stable_for >= OUTPUT_STABLE_SECONDS:
                return

        time.sleep(OUTPUT_POLL_INTERVAL)

    # 超时：再给一个固定兜底等待，避免完全没截到尾部
    time.sleep(min(WAIT_AFTER_SEND_FALLBACK, 30))


def _window_bbox(win):
    try:
        if "AXFrame" in win.ax_attributes:
            f = win.AXFrame
            return (f.x, f.y, f.x + f.width, f.y + f.height)
    except Exception:
        pass
    try:
        p = win.AXPosition
        s = win.AXSize
        return (p.x, p.y, p.x + s.width, p.y + s.height)
    except Exception:
        return None


def create_batch_folder(batch_id):
    folder = BASE_WORK_DIR / f"batch_{batch_id:03d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _return_to_desktop_before_new_trae_instance(
        trae_process_name="Trae CN",
        *,
        hide_trae_processes=True,
):
    """
    在打开第二个及以后的 Trae 工作区（open -n）之前：先回到桌面层，减少仍卡在前一个 Trae 窗口的情况。

    步骤（hide_trae_processes=True 时）：隐藏所有名为「Trae CN」的进程 → 激活 Finder → **Fn+F11**。
    **batch1 发完第一轮后准备开 batch2 时**建议传 ``hide_trae_processes=False``：只 Fn+F11 + Finder，
    不把 Trae 设为不可见，避免部分环境下 ``open -n`` 无法拉起第二个实例。

    另：激活 Finder → 发送 **Fn+F11**（key code 103 + fn down）；若 osascript 失败，再尝试 atomacos。
    """
    esc = (trae_process_name or "Trae CN").replace("\\", "\\\\").replace('"', '\\"')
    hide_block = ""
    if hide_trae_processes:
        hide_block = f'''
    tell application "System Events"
        repeat with p in (every application process whose name is "{esc}")
            try
                set visible of p to false
            end try
        end repeat
    end tell
    delay 0.4
'''
    script = f'''
{hide_block}
    tell application "Finder" to activate
    delay 0.25
    tell application "System Events"
        try
            key code 103
        end try
    end tell
    delay 0.35
    '''
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if r.stderr and r.stderr.strip():
            print(f"osascript(回到桌面 Fn+F11): {r.stderr.strip()}")
    except Exception as e:
        print(f"_return_to_desktop_before_new_trae_instance: {e}")
    try:
        keyboard.hotkey("fn", "f11")
    except Exception:
        pass
    time.sleep(0.45)


def _open_trae_workspace_cmd(path: Path, *, new_instance: bool, bundle_id=None):
    """构造 ``open`` 打开 Trae 工作区的 argv（优先 Bundle ID + 绝对路径）。"""
    path = Path(path).resolve()
    bid = bundle_id or TRAE_BUNDLE_ID
    cmd = [OPEN_EXECUTABLE]
    if new_instance:
        cmd.append("-n")
    if OPEN_TRAE_WITH_BUNDLE_ID:
        cmd.extend(["-b", bid, str(path)])
    else:
        cmd.extend(["-a", TRAE_CN_APP_NAME, str(path)])
    return cmd


def _open_trae_workspace_cmd_app_name(path: Path, *, new_instance: bool):
    """111.py 同款：``open -a "Trae CN" <路径>``（不经 Bundle ID）。"""
    path = Path(path).resolve()
    cmd = [OPEN_EXECUTABLE]
    if new_instance:
        cmd.append("-n")
    cmd.extend(["-a", TRAE_CN_APP_NAME, str(path)])
    return cmd


def run_open_trae_workspace_subprocess(
    path,
    *,
    new_instance=False,
    bundle_id=None,
    log_prefix="[open_trae_workspace]",
    try_app_name_fallback=None,
):
    """
    用 ``open`` 把指定文件夹交给 Trae CN 打开，带重试与 stderr 打印。

    顺序由 ``OPEN_TRAE_WORKSPACE_USE_APP_NAME_FIRST`` 决定（默认 True，与 ``111.py`` 一致）：
    先 ``open -a "Trae CN" <路径>``，失败再视配置尝试 ``open -b <bundle> <路径>``；
    若改为 False，则先 ``-b`` 再视 ``OPEN_TRAE_FALLBACK_APP_NAME_ON_BUNDLE_FAIL`` 尝试 ``-a``。
    """
    path = Path(path).resolve()
    if try_app_name_fallback is None:
        try_app_name_fallback = OPEN_TRAE_FALLBACK_APP_NAME_ON_BUNDLE_FAIL
    bid = bundle_id or TRAE_BUNDLE_ID

    def _run_one_argv(cmd, tag_suffix):
        shell_line = _shell_join_open_argv(cmd)
        print(f"{log_prefix}{tag_suffix} argv={cmd!r}")
        print(f"{log_prefix}{tag_suffix} zsh/bash 可复制（勿写方括号 glob）:\n  {shell_line}")
        last_err = None
        for attempt in range(2):
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    stdin=subprocess.DEVNULL,
                )
                last_err = None
                print(
                    f"{log_prefix}{tag_suffix} subprocess 成功 attempt={attempt + 1} "
                    f"new_instance={new_instance} path={path}"
                )
                break
            except subprocess.CalledProcessError as e:
                last_err = e
                print(
                    f"{log_prefix}{tag_suffix} open 失败 attempt={attempt + 1}: "
                    f"{e.stderr or e.stdout or e}"
                )
                time.sleep(1.2)
        return last_err

    last_err = None

    if OPEN_TRAE_WORKSPACE_USE_APP_NAME_FIRST:
        cmd_a = _open_trae_workspace_cmd_app_name(
            path, new_instance=new_instance
        )
        last_err = _run_one_argv(cmd_a, "[-a优先/111]")
        if last_err is None:
            return path
        if OPEN_TRAE_WITH_BUNDLE_ID and OPEN_TRAE_FALLBACK_BUNDLE_AFTER_APP_NAME_FAIL:
            print(
                f"{log_prefix} -a 方式仍失败，回退为 open -b {bid!r} …"
            )
            cmd_b = _open_trae_workspace_cmd(
                path, new_instance=new_instance, bundle_id=bid
            )
            last_err = _run_one_argv(cmd_b, "[-b回退]")
        if last_err is not None:
            raise last_err
        return path

    if OPEN_TRAE_WITH_BUNDLE_ID:
        cmd = _open_trae_workspace_cmd(
            path, new_instance=new_instance, bundle_id=bid
        )
        last_err = _run_one_argv(cmd, "[-b优先]")
        if last_err is None:
            return path
        if try_app_name_fallback:
            print(
                f"{log_prefix} Bundle ID 方式失败，回退为 open -a {TRAE_CN_APP_NAME!r}（111.py 同款）…"
            )
            cmd_fb = _open_trae_workspace_cmd_app_name(
                path, new_instance=new_instance
            )
            last_err = _run_one_argv(cmd_fb, "[-a回退]")
        if last_err is not None:
            raise last_err
        return path

    cmd = _open_trae_workspace_cmd_app_name(path, new_instance=new_instance)
    last_err = _run_one_argv(cmd, "[-a]")
    if last_err is not None:
        raise last_err
    return path


def ensure_dir_and_open_trae_cn(
    workspace_path,
    *,
    new_instance=False,
    post_open_sleep=None,
    bundle_id=None,
):
    """
    创建目录（若不存在），并用 Trae CN 以该路径作为工作区打开（与 ``open_trae`` 同一套 open 逻辑）。
    返回 ``(app, resolved_path)``；子进程失败会抛 ``CalledProcessError``。
    """
    path = _makedirs_exists_ok(workspace_path)
    bid = bundle_id or TRAE_BUNDLE_ID
    run_open_trae_workspace_subprocess(
        path,
        new_instance=new_instance,
        bundle_id=bid,
        log_prefix="[ensure_dir_and_open_trae_cn]",
    )
    if new_instance and OPEN_TRAE_NEW_INSTANCE_ATTACH_SECOND_OPEN:
        time.sleep(OPEN_TRAE_NEW_INSTANCE_SECOND_GAP_SEC)
        cmd2 = _open_trae_workspace_cmd(
            path, new_instance=False, bundle_id=bid
        )
        try:
            subprocess.run(cmd2, check=False, capture_output=True, text=True)
        except OSError as e:
            print(f"二次 open（无 -n）可忽略: {e}")
    time.sleep(
        post_open_sleep
        if post_open_sleep is not None
        else WAIT_AFTER_OPEN_FOLDER
    )
    app = atomacos.getAppRefByBundleId(bid)
    try:
        app.activate()
    except Exception:
        pass
    time.sleep(0.5)
    return app, path


def _shell_join_open_argv(cmd):
    """
    拼成 zsh/bash 可整行粘贴执行的字符串；路径含空格会自动加引号。
    勿使用 ``open [-n]``：方括号在 zsh 中是 glob，会报错 no matches found: [-n]。
    """
    parts = [str(x) for x in cmd]
    join_fn = getattr(shlex, "join", None)
    if join_fn:
        return join_fn(parts)
    return " ".join(shlex.quote(p) for p in parts)


def _makedirs_exists_ok(path) -> Path:
    """
    使用 ``os.makedirs`` 创建完整目录链（含所有不存在的父目录），已存在则忽略。
    与 ``Path.mkdir(parents=True, exist_ok=True)`` 语义相同；显式用 makedirs 便于对照文档理解。
    """
    p = Path(path).expanduser().resolve()
    os.makedirs(p, exist_ok=True)
    return p


def _try_get_trae_app(bundle_id=None):
    """获取 Trae 应用引用；未运行或异常时返回 None。"""
    bid = bundle_id or TRAE_BUNDLE_ID
    try:
        return atomacos.getAppRefByBundleId(bid)
    except (ValueError, Exception):
        return None


def setup_workspace_and_launch_trae(
        batch_id,
        base_work_dir=None,
        *,
        workspace_parent=None,
        day_subdir=None,
        bundle_id=None,
        open_workspace=True,
        open_workspace_sleep=None,
        wait_after_launch=5.0,
        wait_after_activate=2.0,
):
    """
    1. 创建工作目录：默认 ``<BASE>/<月日>/batch_id>``；若传入 ``workspace_parent`` 则为 ``<workspace_parent>/batch_id>``。
    2. 若 Trae 已运行则 ``activate``，再用 ``open -b <bundle> <目录>`` 打开工作区（子进程失败会抛错）。
    3. 若未运行且 ``open_workspace``：一条命令 ``open -b <bundle> <目录>`` 冷启动并打开该文件夹（避免先空启动再挂目录易失败）。
       若 ``open_workspace`` 为假：仅 ``open -b <bundle>`` 启动应用。

    返回 ``(app, full_dir)``，其中 ``full_dir`` 为 ``Path``。
    """
    bundle_id = bundle_id or TRAE_BUNDLE_ID
    if workspace_parent is not None:
        full_dir = (Path(workspace_parent) / str(batch_id)).resolve()
    else:
        root = Path(BASE_WORK_DIR if base_work_dir is None else base_work_dir)
        day = (
            datetime.now().strftime("%m%d")
            if day_subdir is None
            else str(day_subdir)
        )
        full_dir = (root / day / str(batch_id)).resolve()

    _makedirs_exists_ok(full_dir)
    print(f"[setup_workspace_and_launch_trae] 工作目录: {full_dir}")

    ows = (
        open_workspace_sleep
        if open_workspace_sleep is not None
        else WAIT_AFTER_OPEN_FOLDER_REOPEN
    )

    app = _try_get_trae_app(bundle_id)
    was_running = app is not None

    if was_running:
        try:
            app.activate()
            print("[setup_workspace_and_launch_trae] Trae CN 已运行，已激活")
        except Exception as e:
            print(f"[setup_workspace_and_launch_trae] activate 警告: {e}")
        time.sleep(wait_after_activate)
        if open_workspace:
            run_open_trae_workspace_subprocess(
                full_dir,
                new_instance=False,
                bundle_id=bundle_id,
                log_prefix="[setup_workspace_and_launch_trae]",
            )
            print(
                "[setup_workspace_and_launch_trae] 已在运行实例中打开工作区: "
                f"{full_dir}"
            )
            time.sleep(ows)
    else:
        if open_workspace:
            run_open_trae_workspace_subprocess(
                full_dir,
                new_instance=False,
                bundle_id=bundle_id,
                log_prefix="[setup_workspace_and_launch_trae]",
            )
            print(
                "[setup_workspace_and_launch_trae] 冷启动并打开工作区: "
                f"{full_dir}"
            )
            time.sleep(wait_after_launch)
            app = _try_get_trae_app(bundle_id)
            if app is None:
                raise RuntimeError(
                    "无法启动 Trae CN，请检查 Bundle ID 与权限；"
                    "若 open 已成功，可增大 wait_after_launch"
                )
            time.sleep(wait_after_activate)
            time.sleep(ows)
        else:
            subprocess.run([OPEN_EXECUTABLE, "-b", bundle_id], check=False)
            print(
                "[setup_workspace_and_launch_trae] 正在启动 Trae CN（无工作区路径）…"
            )
            time.sleep(wait_after_launch)
            app = _try_get_trae_app(bundle_id)
            if app is None:
                raise RuntimeError(
                    "无法启动 Trae CN，请检查 Bundle ID（cn.trae.app）与辅助功能权限"
                )
            time.sleep(wait_after_activate)

    app = _try_get_trae_app(bundle_id)
    if app is not None:
        try:
            app.activate()
        except Exception:
            pass

    return app, full_dir


def open_trae(workspace_folder=None, *, post_open_sleep=None, new_instance=False):
    """
    启动或聚焦 Trae CN。若传入 workspace_folder，则用 macOS `open` 打开该路径作为工作区
    （与 create_batch_folder 返回目录一致），便于在该项目上下文中使用 AI 输入框。
    post_open_sleep 为 None 时首次打开用 WAIT_AFTER_OPEN_FOLDER；可传入较小值用于交错循环中反复切换。
    new_instance=True 时使用 ``open -n``，在 Trae 已在运行时仍强制新开一条实例/窗口（多 batch 并行必需）。
    默认用 ``-b cn.trae.app`` 打开，避免应用显示名与「Trae CN」不一致；可选在 ``-n`` 后再一次无 ``-n`` 的 open 挂上工作区（见 OPEN_TRAE_NEW_INSTANCE_ATTACH_SECOND_OPEN）。
    """
    if workspace_folder is not None:
        path = _makedirs_exists_ok(workspace_folder)
        run_open_trae_workspace_subprocess(
            path,
            new_instance=new_instance,
            bundle_id=TRAE_BUNDLE_ID,
            log_prefix="[open_trae]",
        )
        if new_instance and OPEN_TRAE_NEW_INSTANCE_ATTACH_SECOND_OPEN:
            time.sleep(OPEN_TRAE_NEW_INSTANCE_SECOND_GAP_SEC)
            cmd2 = _open_trae_workspace_cmd(
                path, new_instance=False, bundle_id=TRAE_BUNDLE_ID
            )
            try:
                subprocess.run(cmd2, check=False, capture_output=True, text=True)
            except OSError as e:
                print(f"二次 open（无 -n）可忽略: {e}")
        time.sleep(
            post_open_sleep
            if post_open_sleep is not None
            else WAIT_AFTER_OPEN_FOLDER
        )
    else:
        if OPEN_TRAE_WITH_BUNDLE_ID:
            subprocess.run([OPEN_EXECUTABLE, "-b", TRAE_BUNDLE_ID], check=True)
        else:
            subprocess.run([OPEN_EXECUTABLE, "-a", TRAE_CN_APP_NAME], check=True)
        time.sleep(WAIT_AFTER_LAUNCH)
    app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
    try:
        app.activate()
    except Exception:
        pass
    time.sleep(0.5)
    return app


def open_trae_new_instance_at_path(workspace_folder, *, post_open_sleep=None):
    """
    在 Trae CN **已经运行**的前提下，为 ``workspace_folder`` 再开 **一条新实例/新窗口**。

    等价于 ``open_trae(..., new_instance=True)``，即 macOS 的 ``open -n -b <bundle> <路径>``。
    若只想在当前实例里换文件夹、不要新窗口，请用 ``open_trae(..., new_instance=False)``。
    """
    return open_trae(
        workspace_folder,
        post_open_sleep=post_open_sleep,
        new_instance=True,
    )


def find_element(app, criteria):
    """根据 AXRole 与文案子串（支持 | 分隔多选一）递归查找。"""

    def search(elem):
        try:
            role = elem.AXRole
        except Exception:
            return None
        if role == criteria["role"] and _name_criteria_match(criteria.get("name", ""), elem):
            return elem
        for child in _safe_ax_children(elem):
            res = search(child)
            if res:
                return res
        return None

    for win in app.windows():
        found = search(win)
        if found:
            return found
    return None


def _collect_by_role(root, role):
    out = []

    def walk(elem):
        try:
            if elem.AXRole == role:
                out.append(elem)
            for c in _safe_ax_children(elem):
                walk(c)
        except Exception:
            pass

    walk(root)
    return out


def find_chat_input(app):
    """优先按占位符匹配 AXTextArea，其次 AXTextField；仍找不到则取窗口内最靠下的文本框（多为聊了天输入区）。"""
    for crit in (
            INPUT_BOX,
            {"role": "AXTextField", "name": INPUT_BOX.get("name", "")},
    ):
        el = find_element(app, crit)
        if el:
            return el
    best = None
    best_bottom = -1.0
    for win in app.windows():
        try:
            title = (win.AXTitle or "").strip()
            if not title:
                continue
        except Exception:
            continue
        for elem in _collect_by_role(win, "AXTextArea") + _collect_by_role(win, "AXTextField"):
            try:
                f = elem.AXFrame
                bottom = float(f.y + f.height)
            except Exception:
                bottom = 0.0
            if bottom >= best_bottom:
                best_bottom = bottom
                best = elem
    return best


def _set_ax_value(elem, text):
    try:
        elem.AXValue = text
    except Exception:
        try:
            elem.setString("AXValue", text)
        except Exception as e:
            raise RuntimeError(f"无法写入输入框 AXValue: {e}") from e


def _press_ax_button(elem):
    """优先 AXPress；atomacos 亦可能通过 .Press() 映射到 AXPress。"""
    try:
        if "AXPress" in elem.ax_actions:
            elem.AXPress()
            return
    except Exception:
        pass
    press_fn = getattr(elem, "Press", None)
    if callable(press_fn):
        try:
            press_fn()
            return
        except Exception:
            pass
    raise RuntimeError("按钮无可执行动作（无 AXPress / Press）")


def _click_element_center(elem):
    x, y = _elem_center_point(elem)
    mouse.moveTo(x, y)
    time.sleep(0.05)
    mouse.click(x, y)
    time.sleep(0.15)


def _press_send_or_click(elem):
    """无障碍点击失败时，用物理鼠标点按钮中心（图标按钮常见）。"""
    try:
        _try_ax_focus(elem)
        time.sleep(0.08)
        _press_ax_button(elem)
        return
    except Exception:
        try:
            _click_element_center(elem)
        except Exception as e:
            raise RuntimeError(f"发送按钮无法 AXPress 也无法点击中心: {e}") from e


def find_send_button_heuristic(app):
    """
    在窗口底部条内收集 AXButton：优先文案命中 SEND_BUTTON；
    否则取「竖直位置最靠下且水平最靠右」的小按钮（多为绿色上箭头）。
    合并所有带标题主窗口的候选，取全局最高分。
    """
    app = _refresh_trae_app(app)
    name_pat = SEND_BUTTON.get("name", "")
    all_scored = []
    for win in app.windows():
        try:
            if not (win.AXTitle or "").strip():
                continue
        except Exception:
            continue
        bbox = _window_bbox(win)
        if not bbox:
            continue
        x0, y0, x1, y1 = bbox
        win_h = max(y1 - y0, 1.0)
        bottom_line = y0 + win_h * 0.76
        buttons = _collect_by_role(win, "AXButton")
        for b in buttons:
            try:
                f = b.AXFrame
                cy = f.y + f.height / 2.0
                cx = f.x + f.width / 2.0
                if cy < bottom_line:
                    continue
                text_hit = _name_criteria_match(name_pat, b) if name_pat else False
                small = f.width <= 72 and f.height <= 72
                rightness = (cx - x0) / max(x1 - x0, 1.0)
                bottomness = (cy - y0) / win_h
                score = 0.0
                if text_hit:
                    score += 1000.0
                if small:
                    score += 50.0
                score += rightness * 80.0 + bottomness * 40.0
                all_scored.append((score, b))
            except Exception:
                continue
    if all_scored:
        all_scored.sort(key=lambda t: -t[0])
        return all_scored[0][1]
    return None


def _try_send_via_shortcut():
    """多种快捷键，适配 Electron / VS Code 系聊天。"""
    for combo in (
            ("command", "return"),
            ("ctrl", "return"),
            ("shift", "command", "return"),
    ):
        try:
            keyboard.hotkey(*combo)
            time.sleep(0.22)
        except Exception:
            continue


def _simple_focus_and_paste(app, prompt):
    """
    简化流：activate →（可选）点聊天输入区比例坐标 → Cmd+A / Cmd+V。
    与手工「打开 batch 工作区 → 点一下输入条 → 粘贴」一致；不轮询系统前台、不重试第二轮。
    """
    app = _refresh_trae_app(app)
    try:
        app.activate()
    except Exception:
        pass
    time.sleep(WAIT_AFTER_ACTIVATE_BEFORE_PASTE)
    if PASTE_CLICK_BEFORE:
        ok_click = _click_window_fraction(app, CHAT_CLICK_X_FRAC, CHAT_CLICK_Y_FRAC)
        if not ok_click:
            print(
                "[paste] 未命中带标题主窗口，尝试确认前台后再次点击输入区…",
                flush=True,
            )
            _ensure_trae_frontmost(timeout=6.0)
            time.sleep(0.35)
            ok_click = _click_window_fraction(
                _refresh_trae_app(app), CHAT_CLICK_X_FRAC, CHAT_CLICK_Y_FRAC
            )
        if not ok_click:
            print(
                "[paste] 警告：比例点击仍可能未落到 Trae 聊天区，仍将尝试 Cmd+V；"
                "若仍无输入请调 CHAT_CLICK_X_FRAC / CHAT_CLICK_Y_FRAC 或暂时关 TRAE_SIMPLE_OPEN_CLICK_PASTE",
                flush=True,
            )
    for combo in FOCUS_AI_INPUT_HOTKEYS:
        if combo:
            keyboard.hotkey(*combo)
            time.sleep(0.25)
    _copy_to_clipboard(prompt)
    keyboard.hotkey("command", "a")
    time.sleep(0.08)
    keyboard.hotkey("command", "v")
    time.sleep(WAIT_AFTER_FOCUS_CLICK + 0.15)


def trigger_send(app):
    """
    依次：按名查找按钮 → 底部启发式按钮 → AXPress/Press/鼠标点中心 → 快捷键 → 比例点击发送区。
    """
    app = _refresh_trae_app(app)
    if TRAE_SIMPLE_OPEN_CLICK_PASTE:
        try:
            app.activate()
        except Exception:
            pass
        time.sleep(0.12)
    else:
        _ensure_trae_frontmost()
    app = _refresh_trae_app(app)

    send_elem = find_element(app, SEND_BUTTON)
    if send_elem is None:
        send_elem = find_send_button_heuristic(app)

    if send_elem is not None:
        try:
            _press_send_or_click(send_elem)
            if PRESS_ENTER_TO_SEND_AFTER_TRIGGER:
                try:
                    import pyautogui

                    pyautogui.press("enter")
                    time.sleep(0.1)
                except Exception:
                    pass
            return
        except Exception:
            pass

    _try_send_via_shortcut()

    if SEND_CLICK_FALLBACK:
        _click_window_fraction(app, SEND_CLICK_X_FRAC, SEND_CLICK_Y_FRAC)
        time.sleep(0.12)

    if PRESS_ENTER_TO_SEND_AFTER_TRIGGER:
        try:
            import pyautogui

            pyautogui.press("enter")
            time.sleep(0.12)
        except Exception:
            pass


def _paste_prompt_without_finding_input(app, prompt, *, verify_prompt_in_chat=None):
    """
    先确保 Trae 为前台 →（默认）在窗口比例位置点击中间栏聊天输入区 → Cmd+A / Cmd+V。
    若启用校验（默认与 VERIFY_PROMPT_IN_CHAT_AFTER_PASTE 一致），粘贴后检查聊天框 AXValue 是否含提示词。
    ``verify_prompt_in_chat=False`` 可显式关闭该校验（多工作区切换时常用）。

    若 ``TRAE_SIMPLE_OPEN_CLICK_PASTE`` 为 True，则仅 ``activate`` + 点击输入区 + 粘贴，不做长时间前台轮询；
    默认不跑 AX 粘贴校验（仅当 ``verify_prompt_in_chat=True`` 时校验）。
    """
    if TRAE_SIMPLE_OPEN_CLICK_PASTE:
        do_verify = verify_prompt_in_chat is True
        _simple_focus_and_paste(app, prompt)
        if do_verify:
            ok = _chat_input_reflects_prompt(_refresh_trae_app(app), prompt)
            if ok is True:
                return
            raise RuntimeError(
                "粘贴后校验失败：聊天输入框中未检测到提示词（或无障碍读不到输入框）。"
                "请微调 CHAT_CLICK_X_FRAC / CHAT_CLICK_Y_FRAC；或关闭简化流 TRAE_SIMPLE_OPEN_CLICK_PASTE，"
                "或不要传 verify_prompt_in_chat=True。"
            )
        return

    do_verify = (
        VERIFY_PROMPT_IN_CHAT_AFTER_PASTE
        if verify_prompt_in_chat is None
        else bool(verify_prompt_in_chat)
    )
    if not _ensure_trae_frontmost():
        raise RuntimeError(
            f"{ENSURE_TRAE_FRONTMOST_TIMEOUT}s 内未能确认 Trae CN 为前台应用；"
            "键鼠可能发到了 Cursor/终端。请先切到 Trae 或关掉抢焦点的应用。"
        )
    _copy_to_clipboard(prompt)
    app = _refresh_trae_app(app)
    try:
        app.activate()
    except Exception:
        pass
    time.sleep(WAIT_AFTER_ACTIVATE_BEFORE_PASTE)

    for attempt in range(2):
        if PASTE_CLICK_BEFORE:
            _click_window_fraction(app, CHAT_CLICK_X_FRAC, CHAT_CLICK_Y_FRAC)
        for combo in FOCUS_AI_INPUT_HOTKEYS:
            if combo:
                keyboard.hotkey(*combo)
                time.sleep(0.25)
        _ensure_trae_frontmost()
        keyboard.hotkey("command", "a")
        time.sleep(0.1)
        keyboard.hotkey("command", "v")
        time.sleep(WAIT_AFTER_FOCUS_CLICK + 0.2)

        if not do_verify:
            return
        ok = _chat_input_reflects_prompt(app, prompt)
        if ok is True:
            return
        if attempt == 0:
            time.sleep(0.35)
            continue
        break

    if do_verify:
        raise RuntimeError(
            "粘贴后校验失败：聊天输入框中未检测到提示词（或无障碍读不到输入框）。"
            "请微调 CHAT_CLICK_X_FRAC / CHAT_CLICK_Y_FRAC 对准中间栏底部输入条，"
            "或设 FOCUS_AI_INPUT_HOTKEYS；若确认已粘贴成功可读不到 AX，可设 VERIFY_PROMPT_IN_CHAT_AFTER_PASTE = False。"
        )


def send_prompt(app, prompt, *, verify_prompt_in_chat=None):
    p = (prompt or "").strip()
    prev = p[:72] + ("…" if len(p) > 72 else "")
    print(f"[send_prompt] 开始粘贴（预览）: {prev!r}", flush=True)
    _paste_prompt_without_finding_input(
        app, prompt, verify_prompt_in_chat=verify_prompt_in_chat
    )
    print("[send_prompt] 取聊天区快照并触发发送…", flush=True)
    # 发送前快照：用于对比回复是否已开始、是否已停止变化
    snapshot_before = _chat_ui_text_snapshot(_refresh_trae_app(app))

    trigger_send(_refresh_trae_app(app))

    hb = float(OUTPUT_WAIT_HEARTBEAT_SEC or 0.0)
    if hb > 0:
        print(
            f"[send_prompt] 等待本轮输出稳定（最长 {OUTPUT_MAX_WAIT:.0f}s，"
            f"约每 {hb:.0f}s 打印 [wait_output] 进度）…",
            flush=True,
        )
    else:
        print(
            f"[send_prompt] 等待本轮输出稳定（最长 {OUTPUT_MAX_WAIT:.0f}s）…",
            flush=True,
        )
    _wait_for_output_complete(app, snapshot_before)
    print("[send_prompt] 本轮输出等待结束。", flush=True)


def send_prompt_quick(app, prompt, wait_after_send=2.0, *, verify_prompt_in_chat=None):
    """
    粘贴并发送，不等待流式输出结束；用于多 batch 时依次发送各 batch 的「第一轮」，
    再由 WAIT_AFTER_ALL_BATCHES_ROUND1_SEC 统一等待。
    """
    p = (prompt or "").strip()
    prev = p[:72] + ("…" if len(p) > 72 else "")
    print(f"[send_prompt_quick] 粘贴（预览）: {prev!r}", flush=True)
    _paste_prompt_without_finding_input(
        app, prompt, verify_prompt_in_chat=verify_prompt_in_chat
    )
    print("[send_prompt_quick] 触发发送…", flush=True)
    trigger_send(_refresh_trae_app(app))
    time.sleep(wait_after_send)


def _send_prompt_after_workspace_switch(app, prompt):
    """
    在 ``open`` 切换工作区之后调用：可按 ``SEND_PROMPT_SKIP_VERIFY_AFTER_WORKSPACE_SWITCH``
    跳过「粘贴后 AX 校验」，避免 Trae 短暂读不到输入框导致误报。
    """
    if SEND_PROMPT_SKIP_VERIFY_AFTER_WORKSPACE_SWITCH:
        return send_prompt(app, prompt, verify_prompt_in_chat=False)
    return send_prompt(app, prompt)


def _send_prompt_quick_after_workspace_switch(app, prompt, *, wait_after_send=2.0):
    if SEND_PROMPT_SKIP_VERIFY_AFTER_WORKSPACE_SWITCH:
        return send_prompt_quick(
            app,
            prompt,
            wait_after_send=wait_after_send,
            verify_prompt_in_chat=False,
        )
    return send_prompt_quick(app, prompt, wait_after_send=wait_after_send)


def get_output_text(app):
    output_elem = find_element(app, OUTPUT_AREA)
    if not output_elem:
        # 兜底：尝试获取第一个 AXStaticText 内容
        def first_text(elem):
            try:
                if elem.AXRole == "AXStaticText":
                    v = getattr(elem, "AXValue", None) or getattr(elem, "AXTitle", None)
                    if v:
                        return str(v)
            except Exception:
                pass
            for child in _safe_ax_children(elem):
                val = first_text(child)
                if val:
                    return val
            return None

        for win in app.windows():
            text = first_text(win)
            if text:
                return text
        return "[无法获取输出文本]"
    return (
            (getattr(output_elem, "AXValue", None) or getattr(output_elem, "AXTitle", None) or "")
            or ""
    )


def screenshot_region(app, save_path):
    """截图整个 Trae 主窗口（AXFrame / AXPosition+AXSize）。"""
    for win in app.windows():
        try:
            title = (win.AXTitle or "").strip()
            if not title:
                continue
        except Exception:
            continue
        bbox = _window_bbox(win)
        if bbox:
            x0, y0, x1, y1 = bbox
            img = ImageGrab.grab(bbox=(int(x0), int(y0), int(x1), int(y1)))
            img.save(save_path)
            return
    subprocess.run(["screencapture", "-x", str(save_path)])


def run_batch001_prompts_loop(
        prompts_json_path=None,
        output_json_path=None,
        batch_key=None,
        max_rounds=None,
):
    """
    读取 prompts.json 中指定 batch（默认与 BATCH_KEY_DEFAULT 一致，当前为 batch1），最多 max_rounds 条用例；
    每轮：send_prompt 等待输出 → 主窗截图 → get_sessionID → scroll + get_log_file；
    仅回写 output.json 中与该条 User Prompt 对应项的：
    Trae Session ID、日志轨迹、截图（产物/运行结果/对话）（截图字段写入 PNG 绝对路径）。
    """
    import locate_trae_ui as loc

    prompts_json_path = Path(prompts_json_path or PROMPTS_JSON)
    output_json_path = Path(output_json_path or OUTPUT_JSON_FIXED)
    batch_key = batch_key or BATCH_KEY_DEFAULT
    max_rounds = max_rounds if max_rounds is not None else MAX_PROMPT_ROUNDS

    with open(prompts_json_path, "r", encoding="utf-8") as f:
        pdata = json.load(f)
    batch_key, cases = _resolve_batch_key_and_cases(pdata, batch_key)

    n = min(max_rounds, len(cases))
    shot_dir = _SCRIPT_DIR / "output" / "screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)

    rel_workspace = Path(INTERLEAVED_STABLE_RUN_DIR_NAME) / batch_key
    full_dir = _makedirs_exists_ok(BASE_WORK_DIR / rel_workspace)

    app = open_trae(full_dir)
    time.sleep(WAIT_AFTER_OPEN_FOR_INDEX)
    app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
    loc.app = app

    for i in range(n):
        case = cases[i]
        prompt = (case.get("User Prompt") or "").strip()
        if not prompt:
            print(f"跳过第 {i + 1} 条：无 User Prompt")
            continue
        print(f"\n======== 第 {i + 1}/{n} 轮 batch={batch_key} ========")
        print(f"提示词预览: {prompt[:80]}...")

        try:
            send_prompt(app, prompt)
            _ = get_output_text(_refresh_trae_app(app))
            app = _refresh_trae_app(app)
            loc.app = app
        except Exception as e:
            print(f"发送/等待输出异常: {e}")
            save_session_and_log_to_output_json(
                output_json_path,
                "",
                f"自动化异常（发送/输出阶段）: {e}",
                match_user_prompt=prompt,
                batch_key=batch_key,
                screenshot_value="",
            )
            time.sleep(WAIT_BETWEEN_ROUNDS)
            continue

        shot_path = shot_dir / f"{batch_key}_r{i + 1:02d}.png"
        try:
            screenshot_region(app, shot_path)
        except Exception as e:
            print(f"截图异常: {e}")
            shot_path = None

        app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
        loc.app = app
        time.sleep(0.5)
        session_id = loc.get_sessionID()
        time.sleep(1)
        loc.scroll_down()
        time.sleep(1)
        log_trace = loc.get_log_file()

        shot_str = str(shot_path.resolve()) if shot_path else ""
        save_session_and_log_to_output_json(
            output_json_path,
            session_id,
            log_trace,
            match_user_prompt=prompt,
            batch_key=batch_key,
            screenshot_value=shot_str,
        )
        time.sleep(WAIT_BETWEEN_ROUNDS)

    print("\n全部轮次处理结束。")


def run_batch001_case_loop(
        prompts_json_path=None,
        output_json_path=None,
        batch_key=None,
        max_rounds=None,
        wait_after_send=20.3,
):
    """
    从 prompts.json 顺序执行用例（坐标 + pyautogui，与 locate_trae_ui 配合）。

    - **仅一个可用 batch**：行为与历史一致——只打开该 batch 工作区，逐条 ``input_prompt`` →
      回车 → 等待 → ``get_sessionID`` → ``scroll_down`` → ``get_log_file`` → 截图 → 写 ``output.json``。
    - **至少两个 batch**：为 **每个 batch 启动独立 Trae 进程**（第 2 个起 ``open -n``），
      用 PID 绑定 ``locate_trae_ui.app``；每轮按 batch 顺序 **各客户端发** 当前轮提示词，
      再按同顺序 **各客户端采集**：``scroll_down`` → ``get_log_file`` → ``get_sessionID`` → 截图，
      以 ``round_index`` 写 ``output.json``。若有 batch3、batch4… 一并纳入同一轮转。
    """
    import pyautogui
    import locate_trae_ui as loc
    from locate_trae_ui import get_log_file, get_sessionID, input_prompt, scroll_down

    prompts_json_path = Path(prompts_json_path or PROMPTS_JSON)
    output_json_path = Path(output_json_path or OUTPUT_JSON_FIXED)
    batch_key = batch_key or BATCH_KEY_DEFAULT
    max_rounds = max_rounds if max_rounds is not None else MAX_PROMPT_ROUNDS

    with open(prompts_json_path, "r", encoding="utf-8") as f:
        pdata = json.load(f)

    if not isinstance(pdata, dict):
        raise ValueError("prompts JSON 根须为对象 {batch_name: [用例...]}")

    bkeys_all = _natural_batch_keys(pdata)
    if len(bkeys_all) >= 2:
        batch_keys = list(bkeys_all)
        cases_by = {bk: pdata[bk] for bk in batch_keys}
        for bk in batch_keys:
            if not isinstance(cases_by[bk], list) or not cases_by[bk]:
                raise ValueError(f"{bk} 用例列表无效或为空")

        n = min(max_rounds, *(len(cases_by[bk]) for bk in batch_keys))
        if n < 1:
            raise ValueError("多 batch 模式下至少各需 1 条用例")

        shot_dir = _SCRIPT_DIR / "output" / "screenshots"
        shot_dir.mkdir(parents=True, exist_ok=True)

        run_parent = (BASE_WORK_DIR / INTERLEAVED_STABLE_RUN_DIR_NAME).resolve()
        if INTERLEAVED_USE_TIMESTAMPED_RUN_DIR:
            run_parent = (
                BASE_WORK_DIR
                / f"gui_auto_interleaved_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            ).resolve()
        workspaces = {bk: (run_parent / bk).resolve() for bk in batch_keys}
        for bk in batch_keys:
            _makedirs_exists_ok(workspaces[bk])

        print(
            f"\n[case_loop] 多 batch 多客户端：共 {len(batch_keys)} 路 "
            f"{batch_keys!r}，每路独立 Trae（第 2 路起 open -n），共 {n} 轮\n"
        )

        batch_to_pid = {}
        prev_pids = set(_running_bundle_pids())
        for i, bk in enumerate(batch_keys):
            ws = workspaces[bk]
            use_new = i > 0
            if use_new:
                print(
                    f"[case_loop] 回桌面后 open -n 启动新 Trae 并打开工作区: {bk}"
                )
                _return_to_desktop_before_new_trae_instance(hide_trae_processes=False)
                time.sleep(WAIT_AFTER_DESKTOP_BEFORE_OPEN_NEXT_BATCH_SEC)
            ows = (
                WAIT_AFTER_OPEN_FOLDER
                if i == 0
                else WAIT_AFTER_NEW_TRAE_INSTANCE_SEC
            )
            open_trae(ws, post_open_sleep=ows, new_instance=use_new)
            if i == 0:
                time.sleep(WAIT_AFTER_OPEN_FOR_INDEX)
            elif TRAE_LIGHT_OPEN_SKIP_LONG_FOCUS and use_new:
                time.sleep(2.0)
            else:
                time.sleep(max(4, WAIT_AFTER_OPEN_FOR_INDEX // 2))
            now_p = set(_running_bundle_pids())
            fresh = sorted(now_p - prev_pids)
            if fresh:
                pid = fresh[-1]
            elif now_p:
                pid = max(now_p)
                if use_new:
                    print(
                        f"[case_loop] 警告: 未检测到新 PID，{bk} 可能与已有实例共 pid={pid}；"
                        f"请确认 open -n 是否生效"
                    )
            else:
                raise RuntimeError(
                    f"无法检测到 {TRAE_BUNDLE_ID} 进程，无法绑定 {bk}"
                )
            batch_to_pid[bk] = pid
            prev_pids = now_p
            print(f"[case_loop] {bk} → Trae pid={pid} 工作区={ws}")

        def _activate_batch(bk):
            pid = batch_to_pid[bk]
            app = atomacos.getAppRefByPid(pid)
            loc.app = app
            try:
                app.activate()
            except Exception as e:
                print(f"[case_loop] activate {bk} pid={pid}: {e}")
            time.sleep(0.5)

        def _send_only_case(bk, cases, r):
            prompt = (cases[r].get("User Prompt") or "").strip()
            rl = (cases[r].get("轮次") or f"第{r + 1}轮").strip()
            if not prompt:
                print(f"[case_loop] 跳过 {bk} {rl}：无 User Prompt")
                return
            print(
                f"\n[case_loop] 发送 | {bk} pid={batch_to_pid[bk]} {rl} | 用例 {r + 1}/{n}\n"
                f"提示词预览: {prompt[:100]}..."
            )
            _activate_batch(bk)
            input_prompt(prompt)
            time.sleep(1)
            pyautogui.press("enter", 2)
            time.sleep(0.2)
            pyautogui.press("enter", 2)
            print("[case_loop] 已按回车发送")
            time.sleep(wait_after_send)

        def _collect_case(bk, cases, r):
            rl = (cases[r].get("轮次") or f"第{r + 1}轮").strip()
            print(
                f"\n[case_loop] 采集 | {bk} pid={batch_to_pid[bk]} {rl} | "
                f"scroll → get_log_file → get_sessionID → 截图 → output[round_index={r}]"
            )
            _activate_batch(bk)
            try:
                scroll_down()
            except Exception as e:
                print(f"[case_loop] scroll_down 跳过: {e}")
            time.sleep(1)
            try:
                log_trace = get_log_file()
            except Exception as e:
                log_trace = f"get_log_file 异常: {e}"
                print(f"[case_loop] get_log_file 异常: {e}")
            time.sleep(0.8)
            _activate_batch(bk)
            try:
                session_id = get_sessionID()
            except Exception as e:
                session_id = ""
                print(f"[case_loop] get_sessionID 异常: {e}")
            print("[case_loop] Session ID 长度:", len(session_id))

            app = atomacos.getAppRefByPid(batch_to_pid[bk])
            loc.app = app
            shot_path = shot_dir / f"{bk}_{rl}_case_r{r + 1:02d}.png"
            try:
                screenshot_region(app, shot_path)
            except Exception as e:
                print(f"[case_loop] 截图跳过: {e}")
                shot_path = None
            shot_kw = {}
            if shot_path is not None:
                shot_kw["screenshot_value"] = str(shot_path.resolve())
            save_session_and_log_to_output_json(
                output_json_path,
                session_id,
                log_trace,
                batch_key=bk,
                round_index=r,
                **shot_kw,
            )
            time.sleep(WAIT_BETWEEN_ROUNDS)

        for r in range(n):
            print(f"\n######## [case_loop] 第 {r + 1}/{n} 轮：各客户端发送 ########\n")
            for bk in batch_keys:
                _send_only_case(bk, cases_by[bk], r)
            print(f"\n######## [case_loop] 第 {r + 1}/{n} 轮：各客户端采集 ########\n")
            for bk in batch_keys:
                _collect_case(bk, cases_by[bk], r)

        print(f"\n[case_loop] 多 batch 多客户端共 {n} 轮结束。")
        return

    # ---------- 单 batch：原逻辑 ----------
    batch_key, cases = _resolve_batch_key_and_cases(pdata, batch_key)

    n = min(max_rounds, len(cases))
    shot_dir = _SCRIPT_DIR / "output" / "screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)

    # 勿在此处 launchAppByBundleId：会先启动「无工作区」的 Trae，再 open 路径时
    # 往往无法挂上文件夹（与 111.py 仅 ``open -a Trae CN 路径`` 行为不一致）。
    rel_workspace = Path(INTERLEAVED_STABLE_RUN_DIR_NAME) / batch_key
    full_dir = _makedirs_exists_ok(BASE_WORK_DIR / rel_workspace)
    open_trae(full_dir)
    time.sleep(WAIT_AFTER_OPEN_FOR_INDEX)
    loc.app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)

    for i in range(n):
        prompt = (cases[i].get("User Prompt") or "").strip()
        if not prompt:
            print(f"跳过第 {i + 1} 条：无 User Prompt")
            continue
        print(f"\n======== batch={batch_key} 用例 {i + 1}/{n} ========")
        print(f"提示词预览: {prompt[:100]}...")

        loc.app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
        input_prompt(prompt)

        time.sleep(1)
        pyautogui.press("enter", 2)
        time.sleep(0.2)
        pyautogui.press("enter", 2)
        print("已按回车发送")
        time.sleep(wait_after_send)

        loc.app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
        session_id = get_sessionID()
        print("Session ID 长度:", len(session_id))

        time.sleep(1)
        scroll_down()
        time.sleep(1)
        log_trace = get_log_file()
        print("日志轨迹长度:", len(log_trace))

        app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
        loc.app = app
        shot_path = shot_dir / f"{batch_key}_r{i + 1:02d}.png"
        try:
            screenshot_region(app, shot_path)
        except Exception as e:
            print(f"截图跳过: {e}")
            shot_path = None

        shot_kw = {}
        if shot_path is not None:
            shot_kw["screenshot_value"] = str(shot_path.resolve())

        save_session_and_log_to_output_json(
            output_json_path,
            session_id,
            log_trace,
            match_user_prompt=prompt,
            batch_key=batch_key,
            **shot_kw,
        )
        time.sleep(WAIT_BETWEEN_ROUNDS)

    print(f"\n{batch_key} 组内用例全部跑完。")


def _resolve_batch_key_and_cases(pdata: dict, batch_key: str):
    """
    从 prompts 根对象中解析 batch 键与用例列表。
    优先精确匹配 batch_key；若无则尝试 batch001 <-> batch1；
    再否则使用 _natural_batch_keys 的第一个非空列表键。
    """
    if not isinstance(pdata, dict):
        raise ValueError("prompts JSON 根须为对象 {batch_name: [用例...]}")

    def _pull(k):
        v = pdata.get(k)
        if isinstance(v, list) and v:
            return k, v
        return None

    want = (batch_key or BATCH_KEY_DEFAULT).strip()
    hit = _pull(want)
    if hit:
        return hit

    if want == "batch001":
        hit = _pull("batch1")
        if hit:
            print(f"提示：未找到键 'batch001'，已改用 '{hit[0]}'（与 prompts.json 一致）")
            return hit
    if want == "batch1":
        hit = _pull("batch001")
        if hit:
            print(f"提示：未找到键 'batch1'，已改用 '{hit[0]}'")
            return hit

    ordered = _natural_batch_keys(pdata)
    if ordered:
        k = ordered[0]
        print(f"提示：未找到 {want!r}，已改用首个 batch 键 {k!r}")
        return k, pdata[k]

    raise ValueError(
        f"prompts JSON 中无可用的 batch 列表（已尝试 {want!r} 及别名）"
    )


def _natural_batch_keys(pdata: dict):
    """从 prompts.json 根对象中取出值为「用例列表」的键，并按 batch 名末尾数字自然排序（batch2 < batch10）。"""
    keys = [k for k, v in pdata.items() if isinstance(v, list) and v]

    def sort_key(name: str):
        m = re.match(r"^(.*?)(\d+)$", str(name))
        if m:
            return (m.group(1), int(m.group(2)))
        return (str(name), 0)

    return sorted(keys, key=sort_key)


def _prompts_json_at_least_two_batches(path) -> bool:
    """
    判断 ``prompts.json`` 根对象中是否至少有两个可用 batch（值为非空用例列表的键）。
    用于无参数启动时自动选择双 batch 乒乓模式。
    """
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            pdata = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(pdata, dict):
        return False
    return len(_natural_batch_keys(pdata)) >= 2


def run_interleaved_multi_batch_from_prompts_json(
        prompts_json_path=None,
        output_json_path=None,
        max_rounds=None,
        wait_after_all_round1=None,
):
    """
    读取 prompts.json（根为 { batch1: [...], batch2: [...] }），实现多 Trae 工作区交错跑满 N 轮：

    1. 在 ``BASE_WORK_DIR`` 下创建工作区：默认固定为 ``<BASE_WORK_DIR>/<INTERLEAVED_STABLE_RUN_DIR_NAME>/batch1|batch2|…``
       （当前 ``INTERLEAVED_STABLE_RUN_DIR_NAME`` 为 ``0513``，即 ``…/packages/0513/…``）；
       ``INTERLEAVED_USE_TIMESTAMPED_RUN_DIR=True`` 时改为每次 ``gui_auto_interleaved_YYYYMMDD_HHMMSS/…``。创建后写入 ``last_interleaved_workspaces.txt``。
    2. **第一轮发送顺序**：batch1 打开工作区 → 输入第一轮提示词 → **返回桌面（Fn+F11 等）** →
       打开 batch2（带 ``-n`` 的 open）→ 输入第一轮提示词；若有更多 batch，同样在「上一轮第一轮发完」后回桌面再打开下一个。
       全部发完后统一等待 wait_after_all_round1 秒（默认 WAIT_AFTER_ALL_BATCHES_ROUND1_SEC）。
    3. 对 r=0..N-1 循环，对每个 batch 顺序：打开对应工作区 → get_sessionID / get_log_file →
       写入 output.json 该 batch 第 r 条（round_index=r）的「Trae Session ID」「日志轨迹」；
       截图保存到 trae_cn_test_screnshots/<batch_key>/<轮次>.png；
       若 r < N-1，再发送该 batch 的第 r+2 轮 User Prompt（send_prompt 会等待输出稳定）。

    与单 batch 的 ``run_batch001_prompts_loop`` 共用无障碍发送与 locate_trae_ui 取 Session/日志逻辑。
    """
    import locate_trae_ui as loc

    print(
        "\n[interleaved] 警告：本模式依赖「已运行 Trae 时再 open -n」双实例，"
        "在不少环境下不可靠。若无法完成需求，请改用：\n"
        "  python3 trae_auto_runner.py --interleaved-sequential\n"
    )

    prompts_json_path = Path(prompts_json_path or PROMPTS_JSON)
    output_json_path = Path(output_json_path or OUTPUT_JSON_FIXED)
    max_rounds = max_rounds if max_rounds is not None else MAX_PROMPT_ROUNDS
    wait_after_all_round1 = (
        wait_after_all_round1
        if wait_after_all_round1 is not None
        else WAIT_AFTER_ALL_BATCHES_ROUND1_SEC
    )

    with open(prompts_json_path, "r", encoding="utf-8") as f:
        pdata = json.load(f)
    if not isinstance(pdata, dict):
        raise ValueError(f"{prompts_json_path} 根须为对象 {{batch: [用例...]}}")

    batch_keys = _natural_batch_keys(pdata)
    if len(batch_keys) < 1:
        raise ValueError(f"{prompts_json_path} 中无可用的 batch 列表键")

    cases_by = {bk: pdata[bk] for bk in batch_keys}
    for bk in batch_keys:
        if not isinstance(cases_by[bk], list) or not cases_by[bk]:
            raise ValueError(f"{bk} 用例列表无效或为空")

    n_rounds = min(max_rounds, min(len(cases_by[bk]) for bk in batch_keys))

    _makedirs_exists_ok(BASE_WORK_DIR)
    if INTERLEAVED_USE_TIMESTAMPED_RUN_DIR:
        run_parent = (
            BASE_WORK_DIR
            / f"gui_auto_interleaved_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ).resolve()
    else:
        run_parent = (BASE_WORK_DIR / INTERLEAVED_STABLE_RUN_DIR_NAME).resolve()
    _makedirs_exists_ok(run_parent)

    # 阶段 A 里会依次 open Trae；必须在此循环内先为每个 batch（含 batch2）用 makedirs 建好整条路径，
    # 否则 macOS 会报「The file ... does not exist」。open_trae 内也会再 makedirs 一次作兜底。
    workspaces = {}
    for bk in batch_keys:
        wdir = (run_parent / bk).resolve()
        _makedirs_exists_ok(wdir)
        marker = wdir / f"trae_batch_workspace_{datetime.now().strftime('%H%M%S')}.txt"
        marker.write_text(
            f"批次工作区标记\nbatch={bk}\n创建时间={datetime.now().isoformat()}\n",
            encoding="utf-8",
        )
        workspaces[bk] = wdir

    _lines = [
        f"# 由 trae_auto_runner 交错 run 写入 {datetime.now().isoformat()}",
        f"RUN_PARENT={run_parent}",
    ]
    for _bk in batch_keys:
        _lines.append(f"{_bk}={workspaces[_bk]}")
    _lines.append("")
    _lines.append("# zsh 手动打开 batch2（第二实例）示例，请整行复制：")
    if len(batch_keys) > 1:
        _p2 = Path(workspaces[batch_keys[1]]).resolve()
        _lines.append(
            _shell_join_open_argv(
                _open_trae_workspace_cmd(_p2, new_instance=True)
            )
        )
    INTERLEAVED_LAST_PATHS_FILE.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(
        f"\n[interleaved] 工作区已创建；路径清单: {INTERLEAVED_LAST_PATHS_FILE}\n"
        f"[interleaved] RUN_PARENT={run_parent}\n"
    )

    shot_root = _makedirs_exists_ok(SCREENSHOT_INTERLEAVED_ROOT)

    print(
        f"\n=== 阶段 A：各 batch 打开独立工作区并发送「第一轮」"
        f"（共 {len(batch_keys)} 个 batch；batch1 先发第一轮 → 回桌面 → 再 open -n 打开 batch2 并发第一轮）===\n"
    )
    for i, bk in enumerate(batch_keys):
        first_open = i == 0
        use_new = i >= INTERLEAVED_USE_NEW_TRAE_INSTANCE_FROM_BATCH_INDEX
        if use_new:
            post_sleep = WAIT_AFTER_NEW_TRAE_INSTANCE_SEC
        else:
            post_sleep = (
                WAIT_AFTER_OPEN_FOLDER
                if first_open
                else WAIT_AFTER_OPEN_FOLDER_REOPEN
            )
        print(
            f"--- {bk}: 打开 {workspaces[bk]} "
            f"(new_instance={use_new}，batch2 起使用 open -n) ---"
        )
        if use_new:
            _ts = datetime.now().isoformat(timespec="seconds")
            _ws = Path(workspaces[bk]).resolve()
            _cmd_preview = _open_trae_workspace_cmd(_ws, new_instance=True)
            print(
                f"[interleaved][{_ts}] ========== 即将打开 batch2+（new_instance）=========="
            )
            print(
                f"[interleaved][{_ts}] batch_key={bk!r} loop_index={i} "
                f"workspace={_ws} post_open_sleep={post_sleep}s "
                f"OPEN_TRAE_WITH_BUNDLE_ID={OPEN_TRAE_WITH_BUNDLE_ID} "
                f"TRAE_BUNDLE_ID={TRAE_BUNDLE_ID!r}"
            )
            print(
                f"[interleaved][{_ts}] 等价 shell（勿使用 [-n] 字面量）: "
                f"{_shell_join_open_argv(_cmd_preview)}"
            )
        ws_ready = _makedirs_exists_ok(workspaces[bk])
        if use_new:
            print(
                f"[interleaved] 打开 Trae 前已确保工作区目录存在: {ws_ready} "
                f"(is_dir={ws_ready.is_dir()})"
            )
        app = open_trae(
            ws_ready,
            post_open_sleep=post_sleep,
            new_instance=use_new,
        )
        if use_new:
            _ts2 = datetime.now().isoformat(timespec="seconds")
            print(
                f"[interleaved][{_ts2}] open_trae 已返回 batch={bk!r}，"
                f"继续等待索引/就绪并检测前台 Trae"
            )
        loc.app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
        if first_open and not use_new:
            time.sleep(WAIT_AFTER_OPEN_FOR_INDEX)
        elif use_new:
            time.sleep(
                2.0
                if TRAE_LIGHT_OPEN_SKIP_LONG_FOCUS
                else max(4, WAIT_AFTER_OPEN_FOR_INDEX // 2)
            )
        else:
            time.sleep(1.0 if TRAE_LIGHT_OPEN_SKIP_LONG_FOCUS else 3)
        if TRAE_LIGHT_OPEN_SKIP_LONG_FOCUS and use_new:
            _activate_trae_short()
        elif not _ensure_trae_frontmost():
            print("警告：未能确认 Trae CN 为前台，后续粘贴可能发到错误应用")
        app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
        loc.app = app
        p0 = (cases_by[bk][0].get("User Prompt") or "").strip()
        if not p0:
            raise RuntimeError(f"{bk} 第一轮缺少 User Prompt")
        print(f"--- {bk}: 快速发送第一轮（不等待生成结束）---")
        _send_prompt_quick_after_workspace_switch(
            app, p0, wait_after_send=ROUND1_QUICK_SEND_TAIL_SEC
        )

        if i < len(batch_keys) - 1:
            nxt = batch_keys[i + 1]
            print(
                f"--- {bk} 第一轮已发送 → 返回桌面（不隐藏 Trae 进程）→ 等待 "
                f"{WAIT_AFTER_DESKTOP_BEFORE_OPEN_NEXT_BATCH_SEC}s → 再打开 {nxt} ---"
            )
            _return_to_desktop_before_new_trae_instance(hide_trae_processes=False)
            time.sleep(WAIT_AFTER_DESKTOP_BEFORE_OPEN_NEXT_BATCH_SEC)

    print(
        f"\n全部 batch 第一轮已发送，统一等待 {wait_after_all_round1}s …\n"
    )
    time.sleep(wait_after_all_round1)

    print(
        f"\n=== 阶段 B：按轮交错采集并推进（每 batch 共 {n_rounds} 轮）===\n"
    )
    for r in range(n_rounds):
        for bk in batch_keys:
            case = cases_by[bk][r]
            prompt_for_round = (case.get("User Prompt") or "").strip()
            round_label = (case.get("轮次") or f"第{r + 1}轮").strip()
            print(
                f"\n======== {bk} {round_label} | 采集 Session / 日志 / 截图 "
                f"(round_index={r}) ========"
            )

            batch_idx = batch_keys.index(bk)
            if batch_idx >= INTERLEAVED_USE_NEW_TRAE_INSTANCE_FROM_BATCH_INDEX:
                print(f"--- {bk}: 回到桌面后再打开该 batch 工作区 ---")
                _return_to_desktop_before_new_trae_instance()

            app = open_trae(
                workspaces[bk],
                post_open_sleep=max(
                    WAIT_AFTER_OPEN_FOLDER_REOPEN,
                    5,
                ),
                new_instance=False,
            )
            time.sleep(0.6 if TRAE_LIGHT_OPEN_SKIP_LONG_FOCUS else 2)
            if TRAE_LIGHT_OPEN_SKIP_LONG_FOCUS:
                _activate_trae_short()
            elif not _ensure_trae_frontmost():
                print("警告：未能确认 Trae CN 为前台")
            app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
            loc.app = app

            try:
                session_id = loc.get_sessionID()
            except Exception as e:
                session_id = ""
                print(f"get_sessionID 异常: {e}")
            time.sleep(1)
            try:
                loc.scroll_down()
            except Exception as e:
                print(f"scroll_down 异常: {e}")
            time.sleep(1)
            try:
                log_trace = loc.get_log_file()
            except Exception as e:
                log_trace = f"读取日志轨迹失败: {e}"

            batch_shot_dir = shot_root / bk
            batch_shot_dir.mkdir(parents=True, exist_ok=True)
            shot_path = batch_shot_dir / f"{round_label}.png"
            try:
                screenshot_region(app, shot_path)
            except Exception as e:
                print(f"截图异常: {e}")
                shot_path = None

            shot_str = str(shot_path.resolve()) if shot_path else ""
            save_session_and_log_to_output_json(
                output_json_path,
                session_id,
                log_trace,
                batch_key=bk,
                round_index=r,
                screenshot_value=shot_str,
            )

            if r < n_rounds - 1:
                nxt = cases_by[bk][r + 1]
                next_prompt = (nxt.get("User Prompt") or "").strip()
                next_label = (nxt.get("轮次") or "").strip()
                if next_prompt:
                    print(f"--- {bk}: 发送下一轮 {next_label or '(未标轮次)'} ---")
                    try:
                        _send_prompt_after_workspace_switch(app, next_prompt)
                    except Exception as e:
                        print(f"send_prompt 异常: {e}")
                        save_session_and_log_to_output_json(
                            output_json_path,
                            "",
                            f"自动化异常（发送/输出阶段）: {e}",
                            batch_key=bk,
                            round_index=r + 1,
                            screenshot_value="",
                        )
                time.sleep(WAIT_BETWEEN_ROUNDS)

    print("\n多 batch 交错流程全部结束。")


def run_sequential_multi_batch_from_prompts_json(
        prompts_json_path=None,
        output_json_path=None,
        max_rounds=None,
):
    """
    多 batch **按轮交错**（单 Trae、``open`` 切换工作区，**不**使用 ``open -n``）：

    对第 ``r`` 轮依次打开 ``batch1``、``batch2``、… 发送该轮 ``User Prompt`` 并采集写 ``output.json``，
    再进入下一轮。即 **batch1[0] → batch2[0] → batch1[1] → batch2[1] → …**。

    与 ``run_interleaved_multi_batch_from_prompts_json`` 的区别：后者依赖双实例 ``open -n``；
    本函数始终单实例切换目录。
    """
    import locate_trae_ui as loc

    prompts_json_path = Path(prompts_json_path or PROMPTS_JSON)
    output_json_path = Path(output_json_path or OUTPUT_JSON_FIXED)
    max_rounds = max_rounds if max_rounds is not None else MAX_PROMPT_ROUNDS

    with open(prompts_json_path, "r", encoding="utf-8") as f:
        pdata = json.load(f)
    if not isinstance(pdata, dict):
        raise ValueError(f"{prompts_json_path} 根须为对象 {{batch: [用例...]}}")

    batch_keys = _natural_batch_keys(pdata)
    if len(batch_keys) < 1:
        raise ValueError(f"{prompts_json_path} 中无可用的 batch 列表键")

    cases_by = {bk: pdata[bk] for bk in batch_keys}
    for bk in batch_keys:
        if not isinstance(cases_by[bk], list) or not cases_by[bk]:
            raise ValueError(f"{bk} 用例列表无效或为空")

    n_rounds = min(max_rounds, min(len(cases_by[bk]) for bk in batch_keys))

    _makedirs_exists_ok(BASE_WORK_DIR)
    if INTERLEAVED_USE_TIMESTAMPED_RUN_DIR:
        run_parent = (
            BASE_WORK_DIR
            / f"gui_auto_interleaved_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ).resolve()
    else:
        run_parent = (BASE_WORK_DIR / INTERLEAVED_STABLE_RUN_DIR_NAME).resolve()
    workspaces = {bk: (run_parent / bk).resolve() for bk in batch_keys}

    _lines = [
        f"# 顺序多 batch run {datetime.now().isoformat()}",
        f"RUN_PARENT={run_parent}",
    ]
    for _bk in batch_keys:
        _lines.append(f"{_bk}={workspaces[_bk]}")
    INTERLEAVED_LAST_PATHS_FILE.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(
        f"\n[sequential] 路径清单: {INTERLEAVED_LAST_PATHS_FILE}\n"
        f"[sequential] RUN_PARENT={run_parent}\n"
    )

    shot_root = _makedirs_exists_ok(SCREENSHOT_INTERLEAVED_ROOT)

    print(
        "\n=== 顺序多 batch：按轮交错（每轮 batch1→batch2→…，单实例切换工作区）===\n"
    )

    for r in range(n_rounds):
        print(
            f"\n######## [sequential] 第 {r + 1}/{n_rounds} 轮：各 batch 各发一条再采集 ########\n"
        )
        for bi, bk in enumerate(batch_keys):
            if INTERLEAVED_QUIT_TRAE_BETWEEN_BATCHES and bi > 0:
                print("[sequential] batch 间隔：尝试退出 Trae CN 进程 …")
                subprocess.run(["pkill", "-x", "Trae CN"], check=False)
                time.sleep(max(WAIT_BETWEEN_BATCHES, 4))

            is_first_global = r == 0 and bi == 0
            ows = (
                WAIT_AFTER_OPEN_FOLDER
                if is_first_global
                else WAIT_AFTER_OPEN_FOLDER_REOPEN
            )
            print(
                f"\n======== [轮 {r + 1}/{n_rounds}] batch={bk!r} | "
                f"工作区={workspaces[bk]} | round_index={r} ========"
            )
            app, ws = setup_workspace_and_launch_trae(
                bk,
                BASE_WORK_DIR,
                workspace_parent=run_parent if INTERLEAVED_USE_TIMESTAMPED_RUN_DIR else None,
                day_subdir=INTERLEAVED_STABLE_RUN_DIR_NAME,
                open_workspace=True,
                open_workspace_sleep=ows,
                wait_after_launch=5.0,
                wait_after_activate=2.0,
            )
            if ws.resolve() != workspaces[bk].resolve():
                print(
                    f"[sequential] 警告: 工作区路径与预期不一致: got={ws} expect={workspaces[bk]}"
                )
            marker = ws / f"trae_batch_workspace_{datetime.now().strftime('%H%M%S')}.txt"
            marker.write_text(
                f"批次工作区标记（顺序多 batch 按轮交错 + setup_workspace）\n"
                f"batch={bk} round_index={r}\n创建时间={datetime.now().isoformat()}\n",
                encoding="utf-8",
            )

            time.sleep(
                WAIT_AFTER_OPEN_FOR_INDEX
                if is_first_global
                else (1.0 if TRAE_LIGHT_OPEN_SKIP_LONG_FOCUS else 5)
            )
            if is_first_global and SEQUENTIAL_STABILIZE_SEC_FIRST_BATCH > 0:
                print(
                    "[sequential] 冷启动首包：补充 stabilize，等待聊天区可交互…",
                    flush=True,
                )
                _stabilize_trae_after_open_workspace(
                    timeout=min(
                        float(SEQUENTIAL_STABILIZE_SEC_FIRST_BATCH),
                        float(TRAE_FRONTMOST_AFTER_OPEN_TIMEOUT),
                    )
                )
            elif TRAE_LIGHT_OPEN_SKIP_LONG_FOCUS and not is_first_global:
                _activate_trae_short()
            elif not _ensure_trae_frontmost():
                print("警告：未能确认 Trae CN 为前台")
            app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
            loc.app = app

            case = cases_by[bk][r]
            round_label = (case.get("轮次") or f"第{r + 1}轮").strip()
            prompt = (case.get("User Prompt") or "").strip()
            if not prompt:
                print(f"跳过 {bk} {round_label}：无 User Prompt")
                continue

            print(
                f"\n--- [轮 {r + 1}] {bk} {round_label} | send_prompt (round_index={r}) ---"
            )
            try:
                _send_prompt_after_workspace_switch(app, prompt)
            except Exception as e:
                print(f"send_prompt 异常: {e}")
                save_session_and_log_to_output_json(
                    output_json_path,
                    "",
                    f"自动化异常（发送/输出阶段）: {e}",
                    batch_key=bk,
                    round_index=r,
                    screenshot_value="",
                )
                time.sleep(WAIT_BETWEEN_ROUNDS)
                continue

            app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
            loc.app = app

            try:
                session_id = loc.get_sessionID()
            except Exception as e:
                session_id = ""
                print(f"get_sessionID 异常: {e}")
            time.sleep(1)
            try:
                loc.scroll_down()
            except Exception as e:
                print(f"scroll_down 异常: {e}")
            time.sleep(1)
            try:
                log_trace = loc.get_log_file()
            except Exception as e:
                log_trace = f"读取日志轨迹失败: {e}"

            batch_shot_dir = _makedirs_exists_ok(shot_root / bk)
            shot_path = batch_shot_dir / f"{round_label}.png"
            try:
                screenshot_region(app, shot_path)
            except Exception as e:
                print(f"截图异常: {e}")
                shot_path = None

            shot_str = str(shot_path.resolve()) if shot_path else ""
            save_session_and_log_to_output_json(
                output_json_path,
                session_id,
                log_trace,
                batch_key=bk,
                round_index=r,
                screenshot_value=shot_str,
            )
            time.sleep(WAIT_BETWEEN_ROUNDS)

    print("\n顺序多 batch 全部结束。")


def run_pingpong_two_batch_multi_round_from_prompts_json(
        prompts_json_path=None,
        output_json_path=None,
        max_rounds=None,
):
    """
    双 batch **延迟落盘**乒乓（单 Trae，与 ``--pingpong-two-batch`` 对应），流程为：

    1. 打开 batch1 → 仅发送第一轮提示词（等待生成结束，**不**立刻写 output）；
    2. 打开 batch2 → 仅发送第一轮提示词；
    3. 再次打开 batch1 → **截图**、取 Session、**复制**（汇总到剪贴板）、取日志 → **写入 output.json**
       对应 **第一轮** 条目 → 再发送 **batch1 第二轮** 提示词；
    4. 打开 batch2 → 对 **第一轮** 做同样采集并保存 → 再发送 **第二轮** 提示词；

    之后每一轮重复「batch1：先采集上一轮再发本轮 → batch2：先采集上一轮再发本轮」；
    全部发完后对 **两个 batch 的最后一轮** 各做一次采集保存。若仅有一轮用例，则在两轮发送后直接进入两次采集。
    """
    import locate_trae_ui as loc

    prompts_json_path = Path(prompts_json_path or PROMPTS_JSON)
    output_json_path = Path(output_json_path or OUTPUT_JSON_FIXED)
    max_rounds = max_rounds if max_rounds is not None else MAX_PROMPT_ROUNDS

    with open(prompts_json_path, "r", encoding="utf-8") as f:
        pdata = json.load(f)
    if not isinstance(pdata, dict):
        raise ValueError(f"{prompts_json_path} 根须为对象 {{batch: [用例...]}}")

    batch_keys = _natural_batch_keys(pdata)
    if len(batch_keys) < 2:
        raise ValueError(
            f"{prompts_json_path} 中至少需要两个 batch 键（如 batch1、batch2），当前: {batch_keys!r}"
        )
    if len(batch_keys) > 2:
        print(
            f"\n[pingpong] 警告: 检测到 {len(batch_keys)} 个 batch，本模式仅使用前两个: "
            f"{batch_keys[0]!r}, {batch_keys[1]!r}\n"
        )
    b0, b1 = batch_keys[0], batch_keys[1]

    cases_by = {bk: pdata[bk] for bk in batch_keys}
    for bk in (b0, b1):
        if not isinstance(cases_by[bk], list) or not cases_by[bk]:
            raise ValueError(f"{bk} 用例列表无效或为空")

    n_rounds = min(max_rounds, len(cases_by[b0]), len(cases_by[b1]))
    if n_rounds < 1:
        raise ValueError("[pingpong] 两个 batch 至少需要各 1 条用例")

    _makedirs_exists_ok(BASE_WORK_DIR)
    if INTERLEAVED_USE_TIMESTAMPED_RUN_DIR:
        run_parent = (
            BASE_WORK_DIR
            / f"gui_auto_interleaved_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ).resolve()
    else:
        run_parent = (BASE_WORK_DIR / INTERLEAVED_STABLE_RUN_DIR_NAME).resolve()
    workspaces = {bk: (run_parent / bk).resolve() for bk in (b0, b1)}
    for bk in (b0, b1):
        _makedirs_exists_ok(workspaces[bk])

    _lines = [
        f"# pingpong 双 batch（延迟落盘）{datetime.now().isoformat()}",
        f"RUN_PARENT={run_parent}",
        f"{b0}={workspaces[b0]}",
        f"{b1}={workspaces[b1]}",
    ]
    INTERLEAVED_LAST_PATHS_FILE.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(
        f"\n[pingpong] 路径清单: {INTERLEAVED_LAST_PATHS_FILE}\n"
        f"[pingpong] RUN_PARENT={run_parent}\n"
        f"[pingpong] 流程: 两路先发第 1 轮 → 回 {b0} 采第 1 轮并写 JSON 后发第 2 轮 → "
        f"{b1} 采第 1 轮并写后发第 2 轮 → …\n"
    )

    shot_root = _makedirs_exists_ok(SCREENSHOT_INTERLEAVED_ROOT)

    def _open_ws(bk, *, long_wait):
        ows = WAIT_AFTER_OPEN_FOLDER if long_wait else WAIT_AFTER_OPEN_FOLDER_REOPEN
        app = open_trae(workspaces[bk], post_open_sleep=ows, new_instance=False)
        try:
            app.activate()
        except Exception:
            pass
        if TRAE_LIGHT_OPEN_SKIP_LONG_FOCUS and not long_wait:
            _activate_trae_short(app)
            app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
            loc.app = app
            return app
        time.sleep(1.0)
        tmo = TRAE_FRONTMOST_AFTER_OPEN_TIMEOUT if long_wait else 18.0
        if not _stabilize_trae_after_open_workspace(timeout=tmo):
            print(
                f"[pingpong] 警告: {tmo:.0f}s 内未能确认 Trae 为前台（{bk}）。"
                "可手动点一下 Trae 窗口或暂时最小化 PyCharm；脚本仍会尝试 send_prompt。"
            )
        app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
        loc.app = app
        return app

    def _send_only(bk, r, *, phase_label):
        case = cases_by[bk][r]
        prompt = (case.get("User Prompt") or "").strip()
        round_label = (case.get("轮次") or f"第{r + 1}轮").strip()
        if not prompt:
            print(f"[pingpong] 跳过 {bk} {round_label}：无 User Prompt")
            return
        print(
            f"\n[pingpong] {phase_label} | {bk} {round_label} | 仅 send_prompt (round_index={r}) ---"
        )
        app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
        loc.app = app
        try:
            _send_prompt_after_workspace_switch(app, prompt)
        except Exception as e:
            print(f"[pingpong] send_prompt 异常: {e}")
            save_session_and_log_to_output_json(
                output_json_path,
                "",
                f"自动化异常（发送/输出阶段）: {e}",
                batch_key=bk,
                round_index=r,
                screenshot_value="",
            )
        time.sleep(WAIT_BETWEEN_ROUNDS)

    def _collect_save_round(bk, r, *, phase_label):
        """对已在该工作区生成完毕的第 r 轮（0 起）做截图、Session、日志并写 output.json。"""
        case = cases_by[bk][r]
        round_label = (case.get("轮次") or f"第{r + 1}轮").strip()
        print(
            f"\n[pingpong] {phase_label} | {bk} {round_label} | "
            f"采集截图 / Session / 日志 → output[round_index={r}] ---"
        )
        app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
        loc.app = app
        try:
            session_id = loc.get_sessionID()
        except Exception as e:
            session_id = ""
            print(f"[pingpong] get_sessionID 异常: {e}")
        time.sleep(1)
        try:
            loc.scroll_down()
        except Exception as e:
            print(f"[pingpong] scroll_down 异常: {e}")
        time.sleep(1)
        try:
            log_trace = loc.get_log_file()
        except Exception as e:
            log_trace = f"读取日志轨迹失败: {e}"

        clip_blob = (
            f"[{bk} {round_label}]\nTrae Session ID:\n{session_id}\n\n"
            f"日志轨迹:\n{log_trace}"
        )
        try:
            _copy_to_clipboard(clip_blob[:120_000])
            print("[pingpong] 已将 Session + 日志轨迹摘要写入剪贴板（便于粘贴）")
        except Exception as e:
            print(f"[pingpong] 写入剪贴板跳过: {e}")

        batch_shot_dir = _makedirs_exists_ok(shot_root / bk)
        shot_path = batch_shot_dir / f"{round_label}_采集.png"
        try:
            screenshot_region(app, shot_path)
        except Exception as e:
            print(f"[pingpong] 截图异常: {e}")
            shot_path = None
        shot_str = str(shot_path.resolve()) if shot_path else ""
        save_session_and_log_to_output_json(
            output_json_path,
            session_id,
            log_trace,
            batch_key=bk,
            round_index=r,
            screenshot_value=shot_str,
        )
        time.sleep(WAIT_BETWEEN_ROUNDS)

    # ----- 1–2：先发两路第一轮，不落盘 -----
    print("\n######## [pingpong] 步骤 1–2：batch1 与 batch2 各发「第一轮」########\n")
    _open_ws(b0, long_wait=True)
    _send_only(b0, 0, phase_label="步骤1")

    _open_ws(b1, long_wait=False)
    _send_only(b1, 0, phase_label="步骤2")

    # ----- 3–4 及后续：batch1 采上一轮 + 发下一轮；batch2 采上一轮 + 发下一轮 -----
    for r in range(1, n_rounds):
        print(
            f"\n######## [pingpong] 步骤 3–4 循环（推进到第 {r + 1} 轮发送）########\n"
        )
        _open_ws(b0, long_wait=False)
        _collect_save_round(b0, r - 1, phase_label="步骤3" if r == 1 else f"batch1采集第{r}轮")
        _send_only(b0, r, phase_label="步骤3" if r == 1 else f"batch1发第{r + 1}轮")

        _open_ws(b1, long_wait=False)
        _collect_save_round(
            b1,
            r - 1,
            phase_label="步骤4" if r == 1 else f"batch2采集第{r}轮",
        )
        _send_only(b1, r, phase_label="步骤4" if r == 1 else f"batch2发第{r + 1}轮")

    # ----- 最后一轮：两路都已发完，各采一次 -----
    print("\n######## [pingpong] 收尾：采集两路最后一轮 ########\n")
    _open_ws(b0, long_wait=False)
    _collect_save_round(b0, n_rounds - 1, phase_label="收尾-batch1")

    _open_ws(b1, long_wait=False)
    _collect_save_round(b1, n_rounds - 1, phase_label="收尾-batch2")

    print(f"\n[pingpong] 全部结束 — 再次打开 {b0} 工作区。\n")
    _open_ws(b0, long_wait=False)
    print("\n[pingpong] 双 batch（延迟落盘）流程结束。")


def save_round_result(batch_id, round_idx, prompt, output, screenshot_path):
    """保存单轮结果到本地文件夹"""
    batch_folder = LOCAL_SAVE_DIR / f"batch_{batch_id:03d}"
    batch_folder.mkdir(parents=True, exist_ok=True)
    txt_file = batch_folder / f"round_{round_idx:03d}.txt"
    with open(txt_file, 'w', encoding='utf-8') as f:
        f.write(f"批次: {batch_id}\n")
        f.write(f"轮次: {round_idx}\n")
        f.write(f"时间: {datetime.now().isoformat()}\n")
        f.write(f"提示词:\n{prompt}\n\n")
        f.write(f"输出:\n{output}\n")
    # 截图已保存在 screenshot_path，复制到结果目录
    dest_img = batch_folder / f"round_{round_idx:03d}.png"
    shutil.copy(screenshot_path, dest_img)


# def generate_final_report():
#     """生成 Markdown 报告，便于复制到飞书"""
#     report_path = LOCAL_SAVE_DIR / "final_report.md"
#     with open(report_path, 'w', encoding='utf-8') as md:
#         md.write("# Trae 模型测试报告\n\n")
#         batches = sorted([d for d in LOCAL_SAVE_DIR.iterdir() if d.is_dir() and d.name.startswith("batch_")])
#         for batch_dir in batches:
#             batch_id = batch_dir.name.split("_")[1]
#             md.write(f"## 批次 {batch_id}\n\n")
#             rounds = sorted(batch_dir.glob("round_*.txt"))
#             for txt_file in rounds:
#                 round_idx = txt_file.stem.split("_")[1]
#                 # 读取内容
#                 with open(txt_file, 'r', encoding='utf-8') as f:
#                     content = f.read()
#                 # 提取提示词和输出
#                 lines = content.split('\n')
#                 prompt = ""
#                 output = ""
#                 in_output = False
#                 for line in lines:
#                     if line.startswith("提示词:"):
#                         prompt = line.replace("提示词:", "").strip()
#                     elif line.startswith("输出:"):
#                         in_output = True
#                         continue
#                     if in_output:
#                         output += line + "\n"
#                 md.write(f"### 第 {round_idx} 轮\n\n")
#                 md.write(f"**提示词:** {prompt}\n\n")
#                 md.write(f"**输出:**\n{output.strip()}\n\n")
#                 img_rel = f"./batch_{batch_id}/round_{round_idx:03d}.png"
#                 md.write(f"![截图]({img_rel})\n\n")
#     print(f"✅ 报告已生成: {report_path}")
#     print("请打开该 Markdown 文件，全选复制后粘贴到飞书文档（图片可能需要手动重新上传）")

#
# def debug_dump_trae_input_reading():
#     """
#     调试：用系统无障碍 API 查看「当前焦点」与「候选文本框」的 AXValue。
#     用法：先打开并聚焦 Trae CN（可点一下聊天输入区），再执行：
#       python trae_auto_runner.py --dump-input
#     Electron/内嵌 Web 可能不暴露真实输入内容，此时 value 可能为空，需关掉校验或改用截图 OCR。
#     """
#     if not _ensure_trae_frontmost():
#         print("❌ 时限内未确认 Trae CN 为前台，请先切到 Trae 再试。")
#         return
#     app = _refresh_trae_app(None)
#
#     print("\n=== 1) systemwide.AXFocusedUIElement（全系统当前焦点）===")
#     try:
#         sw = atomacos.NativeUIElement.systemwide()
#         if "AXFocusedUIElement" in sw.ax_attributes:
#             fe = sw.AXFocusedUIElement
#             if fe is not None:
#                 try:
#                     app_el = fe.getApplication()
#                     bid = getattr(app_el, "bundle_id", "?")
#                     role = getattr(fe, "AXRole", "?")
#                     val = _safe_ax_value_str(fe)
#                     title = ""
#                     try:
#                         if "AXTitle" in fe.ax_attributes:
#                             title = fe.AXTitle or ""
#                     except Exception:
#                         pass
#                     print(f"  bundle_id={bid}")
#                     print(f"  role={role} AXTitle={title!r}")
#                     print(f"  AXValue 长度={len(val)} 预览={val[:400]!r}")
#                 except Exception as e:
#                     print(f"  读焦点控件失败: {e}")
#             else:
#                 print("  (当前无焦点控件)")
#         else:
#             print("  系统对象不支持 AXFocusedUIElement")
#     except Exception as e:
#         print(f"  异常: {e}")
#
#     print("\n=== 2) find_chat_input() 命中 ===")
#     el = find_chat_input(app)
#     if el:
#         v = _safe_ax_value_str(el)
#         print(f"  role={el.AXRole} AXValue 长度={len(v)} 预览={v[:400]!r}")
#     else:
#         print("  (未命中)")
#
#     print("\n=== 3) 各主窗口内 TextArea/TextField（按底部 y 降序，最多 15 条）===")
#     shown = False
#     for win in app.windows():
#         try:
#             wtitle = (win.AXTitle or "").strip()
#             if not wtitle:
#                 continue
#         except Exception:
#             continue
#         print(f"  窗口: {wtitle!r}")
#         scored = []
#         for elem in _collect_by_role(win, "AXTextArea") + _collect_by_role(win, "AXTextField"):
#             try:
#                 f = elem.AXFrame
#                 bottom = float(f.y + f.height)
#             except Exception:
#                 bottom = 0.0
#             r = getattr(elem, "AXRole", "?")
#             v = _safe_ax_value_str(elem)
#             scored.append((bottom, r, v))
#         scored.sort(key=lambda t: -t[0])
#         for i, (bottom, role, val) in enumerate(scored[:15]):
#             shown = True
#             print(f"    [{i}] bottom={bottom:.0f} role={role} len={len(val)} {val[:200]!r}")
#         break
#     if not shown:
#         print("    (无任何文本类控件)")
#
#     print(
#         "\n完成。若 AXValue 始终为空，说明 Trae 未把聊天内容暴露给 macOS 无障碍，只能靠截图 OCR 或关闭 VERIFY_PROMPT_IN_CHAT_AFTER_PASTE。\n")


# def main():
#     prompts = load_prompts(PROMPTS_FILE)
#     BASE_WORK_DIR.mkdir(parents=True, exist_ok=True)
#     LOCAL_SAVE_DIR.mkdir(parents=True, exist_ok=True)
#
#     round_counter = 0
#     batch_id = 1
#
#     while round_counter < TOTAL_ROUNDS:
#         print(f"\n🚀 开始处理批次 {batch_id}，剩余轮次: {TOTAL_ROUNDS - round_counter}")
#         batch_folder = create_batch_folder(batch_id)
#         print(f"   📂 已在 Trae 中打开工作区: {batch_folder}")
#         app = open_trae(batch_folder)
#
#         for j in range(BATCH_SIZE):
#             if round_counter >= TOTAL_ROUNDS:
#                 break
#             prompt = prompts[round_counter]
#             print(f"   第 {round_counter + 1} 轮 -> 提示词: {prompt[:50]}...")
#             try:
#                 _send_prompt_after_workspace_switch(app, prompt)
#                 output = get_output_text(app)
#                 screenshot_path = batch_folder / f"round_{round_counter + 1:03d}.png"
#                 screenshot_region(app, screenshot_path)
#                 save_round_result(batch_id, round_counter + 1, prompt, output, screenshot_path)
#                 print(f"   ✅ 已保存")
#             except Exception as e:
#                 print(f"   ❌ 出错: {e}")
#                 # 继续下一轮，尽量不中断
#             round_counter += 1
#             time.sleep(WAIT_BETWEEN_ROUNDS)
#
#         # if CLOSE_TRAE_AFTER_EACH_BATCH:
#         #     close_trae()
#         batch_id += 1
#         time.sleep(WAIT_BETWEEN_BATCHES)
#
#     print("\n🎉 全部自动化完成！")
#     generate_final_report()


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "Trae CN 自动化入口。不传子命令时：若 prompts.json 至少含两个 batch，"
            "则自动执行双 batch 乒乓（与 --pingpong-two-batch 相同）；否则执行原 "
            "run_batch001_case_loop（坐标流）。"
        )
    )
    parser.add_argument(
        "--open-workspace",
        metavar="DIR",
        dest="open_workspace_path",
        help="创建目录（若不存在）后以 Trae CN 打开该路径为工作区，然后退出",
    )
    parser.add_argument(
        "--open-workspace-new-instance",
        action="store_true",
        help="与 --open-workspace 合用：使用 open -n 新开一条 Trae 实例",
    )
    parser.add_argument(
        "--interleaved",
        action="store_true",
        help="多 batch 交错（双 open -n 实例）：环境要求高，易失败；更稳请用 --interleaved-sequential",
    )
    parser.add_argument(
        "--interleaved-sequential",
        action="store_true",
        help=(
            "多 batch 按轮顺序：第 r 轮先 batch1 再 batch2（单 Trae、切换工作区）；"
            "与 --pingpong-two-batch 二选一"
        ),
    )
    parser.add_argument(
        "--pingpong-two-batch",
        action="store_true",
        help=(
            "显式启用双 batch 乒乓（与「无参数且 prompts 含双 batch」时自动行为相同）："
            "先发两路第 1 轮；再回 batch1 采集第 1 轮写 output 并发第 2 轮，"
            "再 batch2 采集第 1 轮写并发第 2 轮；如此交替，最后各采最后一轮"
        ),
    )
    parser.add_argument(
        "--legacy-case-loop",
        action="store_true",
        help=(
            "无其它子命令时：强制使用原 run_batch001_case_loop（单 batch 坐标流循环写 output），"
            "即使 prompts.json 中有多个 batch"
        ),
    )
    parser.add_argument(
        "--batch-loop",
        action="store_true",
        help="单 batch 多轮：send_prompt 无障碍流程 + 写 output.json（默认 batch 键见 BATCH_KEY_DEFAULT）",
    )
    parser.add_argument(
        "--setup-workspace-demo",
        action="store_true",
        help="仅演示 setup_workspace_and_launch_trae(batch1) 后退出（建目录、激活/启动 Trae、打开工作区）",
    )
    args = parser.parse_args()

    if args.open_workspace_path:
        app, work_dir = ensure_dir_and_open_trae_cn(
            args.open_workspace_path,
            new_instance=args.open_workspace_new_instance,
        )
        print(f"工作区目录: {work_dir}\nApp: {app}")
        sys.exit(0)

    if args.setup_workspace_demo:
        app, work_dir = setup_workspace_and_launch_trae(
            BATCH_KEY_DEFAULT,
            BASE_WORK_DIR,
            day_subdir=INTERLEAVED_STABLE_RUN_DIR_NAME,
            open_workspace=True,
        )
        print(f"App: {app}\n工作目录: {work_dir}")
    elif args.interleaved_sequential and args.pingpong_two_batch:
        print("错误: --interleaved-sequential 与 --pingpong-two-batch 不能同时使用", file=sys.stderr)
        sys.exit(2)
    elif args.pingpong_two_batch:
        run_pingpong_two_batch_multi_round_from_prompts_json(
            prompts_json_path=PROMPTS_JSON,
            output_json_path=OUTPUT_JSON_FIXED,
            max_rounds=MAX_PROMPT_ROUNDS,
        )
    elif args.interleaved_sequential:
        run_sequential_multi_batch_from_prompts_json(
            prompts_json_path=PROMPTS_JSON,
            output_json_path=OUTPUT_JSON_FIXED,
            max_rounds=MAX_PROMPT_ROUNDS,
        )
    elif args.interleaved:
        run_interleaved_multi_batch_from_prompts_json(
            prompts_json_path=PROMPTS_JSON,
            output_json_path=OUTPUT_JSON_FIXED,
            max_rounds=MAX_PROMPT_ROUNDS,
        )
    elif args.batch_loop:
        run_batch001_prompts_loop(
            prompts_json_path=PROMPTS_JSON,
            output_json_path=OUTPUT_JSON_FIXED,
            batch_key=BATCH_KEY_DEFAULT,
            max_rounds=MAX_PROMPT_ROUNDS,
        )
    else:
        if args.legacy_case_loop:
            print(
                "\n[main] --legacy-case-loop：使用原 run_batch001_case_loop（坐标流）\n"
            )
            run_batch001_case_loop(
                prompts_json_path=PROMPTS_JSON,
                output_json_path=OUTPUT_JSON_FIXED,
                batch_key=BATCH_KEY_DEFAULT,
                max_rounds=MAX_PROMPT_ROUNDS,
            )
        elif _prompts_json_at_least_two_batches(PROMPTS_JSON):
            print(
                "\n[main] prompts.json 含至少两个 batch，"
                "自动运行双 batch 乒乓（send_prompt + 延迟写 output，等同 --pingpong-two-batch）\n"
            )
            run_pingpong_two_batch_multi_round_from_prompts_json(
                prompts_json_path=PROMPTS_JSON,
                output_json_path=OUTPUT_JSON_FIXED,
                max_rounds=MAX_PROMPT_ROUNDS,
            )
        else:
            print(
                "\n[main] 仅检测到单 batch 或未读到多 batch，"
                "使用原 run_batch001_case_loop（坐标流循环写 output）\n"
            )
            run_batch001_case_loop(
                prompts_json_path=PROMPTS_JSON,
                output_json_path=OUTPUT_JSON_FIXED,
                batch_key=BATCH_KEY_DEFAULT,
                max_rounds=MAX_PROMPT_ROUNDS,
            )
