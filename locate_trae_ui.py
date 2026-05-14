#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import time
import atomacos
import pyautogui

# 获取命令：osascript -e 'id of app "Trae CN"'
# 请替换为你的 Trae CN 实际的 Bundle ID
TRAE_BUNDLE_ID = "cn.trae.app"  # 如果不确定，可以运行下面被注释的命令获取
try:
    app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
except ValueError:
    # Trae 未启动时导入本模块（如 python trae_auto_runner.py --help）不得失败；运行中由 trae_auto_runner 赋值 loc.app
    app = None


def print_element_tree(element, indent=0):
    """
    调试用：递归打印从 element 起的整棵无障碍子树（Role / Title / Label）。
    用于在 Trae 里「获取/浏览」所有子 element 的概览；树很大时终端会刷屏。
    """
    try:
        role = element.AXRole if hasattr(element, "AXRole") else "Unknown"
        title = element.AXTitle if hasattr(element, "AXTitle") else ""
        label = element.AXLabel if hasattr(element, "AXLabel") else ""
        print(" " * indent + f"Role: {role}, Title: {title}, Label: {label}")
    except Exception:
        print(" " * indent + "Element with no readable attributes")

    if not hasattr(element, "AXChildren"):
        return
    try:
        children = element.AXChildren
        if not children:
            return
        for child in children:
            print_element_tree(child, indent + 2)
    except Exception:
        pass


# 读取剪贴板内容
def get_clipboard():
    result = subprocess.run(["osascript", "-e", "the clipboard as text"],
                            capture_output=True, text=True)
    return result.stdout.strip()


def save_file(clipboard_content):
    # 5. 保存到文件（可选）
    with open("output.txt", "w", encoding="utf-8") as f:
        f.write(clipboard_content)


def find_textarea(element):
    try:
        role = getattr(element, 'AXRole', '')
        if role == 'AXTextArea':
            return element
        if hasattr(element, 'AXChildren'):
            for child in element.AXChildren:
                found = find_textarea(child)
                if found:
                    print('fund')
                    return found
    except:
        pass
    return None


def find_all_thought_buttons(element, results=None):
    """
    递归查找所有标题包含“思考过程”的 AXButton，返回列表
    """
    if results is None:
        results = []
    try:
        role = getattr(element, 'AXRole', '')
        if role == 'AXButton':
            title = getattr(element, 'AXTitle', '') or getattr(element, 'AXLabel', '')
            if '思考过程' in title:
                results.append(element)
        if hasattr(element, 'AXChildren'):
            for child in element.AXChildren:
                find_all_thought_buttons(child, results)
    except Exception:
        pass
    return results


def _ax_children_list(elem):
    try:
        if hasattr(elem, "AXChildren") and elem.AXChildren:
            return list(elem.AXChildren)
    except Exception:
        pass
    return []


def find_ax_button_by_title(element, title_text, *, exact=True):
    """
    在无障碍子树中查找 AXButton，使其 AXTitle 或 AXLabel 与 title_text 匹配。
    exact=True 时做 strip 后全等；否则为子串包含。
    """
    want = (title_text or "").strip()
    if not want:
        return None
    try:
        role = getattr(element, "AXRole", "")
        if role == "AXButton":
            t = (getattr(element, "AXTitle", None) or "").strip()
            lbl = (getattr(element, "AXLabel", None) or "").strip()
            if exact:
                if t == want or lbl == want:
                    return element
            else:
                if want in t or want in lbl:
                    return element
        for child in _ax_children_list(element):
            found = find_ax_button_by_title(child, title_text, exact=exact)
            if found is not None:
                return found
    except Exception:
        pass
    return None


def _press_or_click_ax_button(elem):
    """优先 AXPress / Press，失败则点击控件几何中心。"""
    try:
        if "AXPress" in elem.ax_actions:
            elem.AXPress()
            return True
    except Exception:
        pass
    press_fn = getattr(elem, "Press", None)
    if callable(press_fn):
        try:
            press_fn()
            return True
        except Exception:
            pass
    try:
        f = elem.AXFrame
        cx = int(f.x + f.width / 2)
        cy = int(f.y + f.height / 2)
        pyautogui.click(cx, cy)
        return True
    except Exception:
        return False


def click_keep_all_if_present(root=None):
    """
    若存在 Title/Label 为「全部保留」的 AXButton，则点击一次（用于日志面板等多文件合并场景）。
    """
    root = root or app
    btn = find_ax_button_by_title(root, "全部保留", exact=True)
    if btn is None:
        return False
    if _press_or_click_ax_button(btn):
        print('已点击「全部保留」')
        time.sleep(0.45)
        return True
    print("发现「全部保留」按钮但点击失败")
    return False


def click_run_button_until_gone(root=None, max_clicks=100, pause_after_click=0.45):
    """
    若无障碍树中存在文案含「运行」的 AXButton，则反复定位并点击，
    直到该按钮不再出现或达到 max_clicks 次（防止死循环）。
    每次循环前会刷新 Trae 应用引用，避免 UI 树过期。
    """
    clicks = 0
    root = root or app
    while clicks < max_clicks:
        try:
            root = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
        except Exception:
            root = root or app
        btn = find_ax_button_by_title(root, "运行", exact=False)
        if btn is None:
            if clicks:
                print(f"「运行」按钮已消失（共点击 {clicks} 次）")
            return clicks
        if not _press_or_click_ax_button(btn):
            print("发现「运行」按钮但点击失败，停止")
            break
        clicks += 1
        print(f"已点击「运行」({clicks})")
        time.sleep(pause_after_click)
    try:
        root = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
    except Exception:
        root = app
    if clicks >= max_clicks and find_ax_button_by_title(root, "运行", exact=False):
        print(f"警告：「运行」在 {max_clicks} 次点击后仍存在，停止等待其消失")
    return clicks





def input_prompt(test_prompt):
    input_box = find_textarea(app)
    print(input_box)
    time.sleep(0.1)

    if input_box:
        # 聚焦输入框
        click_x, click_y = 330, 715
        # click_x, click_y = 838, 1496
        pyautogui.doubleClick(click_x, click_y)
        time.sleep(0.2)
        # 输入文本
        # input_box.AXValue = "你的测试提示词"
        pyautogui.hotkey('command', 'a')
        time.sleep(0.1)
        pyautogui.press('delete')
        time.sleep(0.1)

        # 方法1：通过剪贴板粘贴（推荐，支持中文）
        # test_prompt = "你的测试提示词你好你是水实打实的"
        subprocess.run("pbcopy", text=True, input=test_prompt)
        pyautogui.hotkey('command', 'v')

        print("文本已输入")
    else:
        print("无法定位输入框")


def get_sessionID():
    """
    双击 SOLO Coder 区域后 Cmd+C，从剪贴板读取 Session 文本并返回。
    调用方负责把返回值写入 output.json 的「Trae Session ID」字段。
    """
    click_run_button_until_gone()
    coord = get_last_thought_button_coord_with_adaptive_scroll(
        app, min_y=100, max_retries=10)
    if not coord:
        print("无法定位")
        return ""
    solo_y = coord[1] - 50
    pyautogui.click(coord[0], solo_y)
    time.sleep(0.3)
    pyautogui.doubleClick(coord[0], solo_y)

    print(f"已点击 SOLO Coder 近似坐标: ({coord[0]}, {solo_y})")
    time.sleep(0.5)
    pyautogui.hotkey("command", "c")
    time.sleep(0.35)
    session = get_clipboard().strip()
    if session:
        preview = session[:200] + "..." if len(session) > 200 else session
        print(f"剪贴板 Session 预览: {preview!r}")
    else:
        print("警告：剪贴板为空，可能未选中可复制文本")
    return session


def get_log_file():
    """
    复制日志到剪贴板：若有「运行」则点到消失；若有「全部保留」则点一次；
    再点复制按钮坐标；读剪贴板并可选写入 output.txt。
    """
    click_run_button_until_gone()
    click_keep_all_if_present()

    click_x, click_y = 638, 639
    pyautogui.click(click_x, click_y)
    time.sleep(0.3)
    pyautogui.click(click_x, click_y)

    # 2. 等待剪贴板更新（关键！）
    time.sleep(0.3)
    clipboard_content = get_clipboard()

    # 4. 保存到变量（可直接使用）
    print("复制的内容:", clipboard_content)

    # 5. 保存到文件（可选）
    save_file(clipboard_content)
    return clipboard_content


def scroll_down():
    time.sleep(2)
    pyautogui.click(400,500)
    pyautogui.scroll(-50000, x=400, y=500)


def get_last_thought_button_coord_with_adaptive_scroll(app,
                                                       down_scrolls=10,
                                                       up_scrolls=10,
                                                       scroll_amount=500,
                                                       click_coord=(400, 500),
                                                       wait=0.3,
                                                       min_y=100,
                                                       max_retries=10):
    """
    自适应滚动查找最后一个“思考过程”按钮，并在找到后确保其 Y 坐标 >= min_y。
    如果 Y < min_y，则向上滚动（正数）半屏并重新获取坐标，最多重试 max_retries 次（默认 10）。
    """
    def _get_button_coord(buttons):
        if not buttons:
            return None
        last_btn = buttons[-1]
        frame = last_btn.AXFrame
        cx = frame.x + frame.width // 2
        cy = frame.y + frame.height // 2
        return (cx, cy)

    # 原有滚动查找逻辑（略作修改）
    def _find_via_scroll(first_direction='down'):
        # 先尝试不滚动
        buttons = find_all_thought_buttons(app)
        coord = _get_button_coord(buttons)
        if coord:
            return coord
        # 向下滚动尝试
        if first_direction == 'down':
            for i in range(down_scrolls):
                pyautogui.click(*click_coord)
                pyautogui.scroll(-scroll_amount)   # 向下滚动
                time.sleep(wait)
                buttons = find_all_thought_buttons(app)
                coord = _get_button_coord(buttons)
                if coord:
                    return coord
            # 向下未找到，回到顶部再向上尝试
            pyautogui.click(*click_coord)
            pyautogui.scroll(down_scrolls * scroll_amount)  # 回到顶部
            time.sleep(wait)
            for i in range(up_scrolls):
                pyautogui.click(*click_coord)
                pyautogui.scroll(scroll_amount)    # 向上滚动
                time.sleep(wait)
                buttons = find_all_thought_buttons(app)
                coord = _get_button_coord(buttons)
                if coord:
                    return coord
        else:
            # 直接向上尝试
            for i in range(up_scrolls):
                pyautogui.click(*click_coord)
                pyautogui.scroll(scroll_amount)
                time.sleep(wait)
                buttons = find_all_thought_buttons(app)
                coord = _get_button_coord(buttons)
                if coord:
                    return coord
        return None

    # 1. 先找到按钮（无论Y坐标）
    coord = _find_via_scroll()
    if not coord:
        print("未找到思考过程按钮")
        return None

    cx, cy = coord
    print(f"找到思考过程按钮，初始坐标: ({cx}, {cy})")

    # 2. 如果Y坐标小于阈值，向上滚动调整
    for attempt in range(max_retries):
        if cy >= min_y:
            print(f"Y坐标 {cy} 已达到要求")
            return (cx, cy)
        print(f"Y坐标 {cy} < {min_y}，向上滚动半屏...")
        pyautogui.click(*click_coord)
        pyautogui.scroll(scroll_amount)   # 正数 = 向上滚动 = 按钮向下移动
        time.sleep(wait)
        # 重新获取按钮坐标（注意：滚动后按钮可能变化，需要重新查找）
        new_buttons = find_all_thought_buttons(app)
        new_coord = _get_button_coord(new_buttons)
        if not new_coord:
            print("滚动后按钮消失，停止调整")
            break
        cx, cy = new_coord
        print(f"滚动后新坐标: ({cx}, {cy})")

    # 如果最终仍小于阈值，仍返回当前坐标（避免无限循环）
    if cy < min_y:
        print(f"警告：重试 {max_retries} 次后 Y坐标仍为 {cy}，将使用当前坐标")
    return (cx, cy)
# def get_last_thought_button_coord(app):
#     # 直接调用带自适应滚动的版本
#     return get_last_thought_button_coord_with_adaptive_scroll(app)


if __name__ == "__main__":
    import atomacos
    import pyautogui

    atomacos.launchAppByBundleId("cn.trae.app")
    app = atomacos.getAppRefByBundleId("cn.trae.app")

    # 调试：打印整棵无障碍树（输出量可能很大）
    print_element_tree(app)

    time.sleep(2)
    get_sessionID()
    scroll_down()
    get_log_file()
