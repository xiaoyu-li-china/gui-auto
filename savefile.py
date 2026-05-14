import json
import os
from datetime import datetime
from pathlib import Path

from locate_trae_ui import *


WAIT_AFTER_SUBMIT = 10 * 60

_SCRIPT_DIR = Path(__file__).resolve().parent


def read_prompt_from_json(file_path):
    """
    从 JSON 文件中读取 User Prompt 字段。
    支持两种格式：
    1. 文件根是一个数组，每个元素包含 "User Prompt"。
    2. 文件根是一个对象，键为 batch name，值为数组。
    返回第一个匹配的提示词字符串，或 None。
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        print(data)

    # 情况1：直接是数组
    if isinstance(data, list):
        if data and "User Prompt" in data[0]:
            return data[0]["User Prompt"]
    # 情况2：对象包含 batch 键
    elif isinstance(data, dict):
        for key, value in data.items():
            print(key,value)
            if isinstance(value, list) and value and "User Prompt" in value[0]:
                return value[0]["User Prompt"]
    return None


OUTPUT_SCREENSHOT_KEY = "截图（产物/运行结果/对话）"


def save_session_and_log_to_output_json(
        output_json_path,
        session_id,
        log_trace,
        *,
        match_user_prompt=None,
        batch_key=None,
        screenshot_value=None,
        round_index=None,
):
    """
    仅更新 output.json 中匹配用例的以下字段（不改动其余键）：
    「Trae Session ID」「日志轨迹」；若传入 screenshot_value，同时更新「截图（产物/运行结果/对话）」。
    默认使用文件中第一个 batch 键；match_user_prompt 按 User Prompt 全文匹配（strip 后）；
    匹配不到则更新该 batch 的第一条。
    若传入 round_index（0 起），则直接更新该 batch 列表中对应下标的条目（优先于 match_user_prompt）。
    """
    path = Path(output_json_path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data:
        raise ValueError("JSON 根须为对象且非空，例如 {\"batch001\": [...] }")
    key = batch_key
    if key is None:
        key = next(iter(data.keys()))
    if key not in data or not isinstance(data[key], list):
        raise ValueError(f"JSON 中缺少列表字段: {key!r}")
    cases = data[key]
    idx = 0
    if round_index is not None:
        idx = int(round_index)
        if idx < 0 or idx >= len(cases):
            raise ValueError(f"round_index={idx} 越界，{key!r} 共 {len(cases)} 条用例")
    elif match_user_prompt is not None:
        m = (match_user_prompt or "").strip()
        for i, case in enumerate(cases):
            if isinstance(case, dict) and (case.get("User Prompt") or "").strip() == m:
                idx = i
                break
    if not cases or not isinstance(cases[idx], dict):
        raise ValueError(f"无法在 {key!r} 下找到可更新的用例对象")
    cases[idx]["Trae Session ID"] = session_id if session_id is not None else ""
    cases[idx]["日志轨迹"] = log_trace if log_trace is not None else ""
    if screenshot_value is not None:
        cases[idx][OUTPUT_SCREENSHOT_KEY] = screenshot_value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    extra = f" / {OUTPUT_SCREENSHOT_KEY}" if screenshot_value is not None else ""
    print(f"已写入 {path}：{key}[{idx}] Trae Session ID / 日志轨迹{extra}")


def run_single_test_case(case, *, batch_key, output_json_path):
    """对单条用例 dict 执行：发 prompt → 取 Session → 滚底 → 取日志 → 写回 output_json。"""
    if not isinstance(case, dict):
        raise TypeError("case 须为 dict")
    prompt = case.get("User Prompt")
    if not prompt:
        print("警告：用例缺少 User Prompt，跳过")
        return case

    input_prompt(prompt)
    pyautogui.press("enter")
    print("已按回车发送")
    time.sleep(WAIT_AFTER_SUBMIT)

    session_id = get_sessionID()
    print(f"获取到的 Session ID 长度: {len(session_id)}")

    time.sleep(1)
    scroll_down()
    time.sleep(1)
    log_trace = get_log_file()
    print(f"获取到日志轨迹长度: {len(log_trace)}")

    save_session_and_log_to_output_json(
        output_json_path,
        session_id,
        log_trace,
        match_user_prompt=prompt,
        batch_key=batch_key,
    )
    case["Trae Session ID"] = session_id
    case["日志轨迹"] = log_trace
    return case


def run_single_test(file_path, output_json_path=None):
    """从 JSON 取第一条用例并执行自动化，结果写入 output_json_path（默认同目录 output.json）。"""
    path = Path(file_path)
    out = Path(output_json_path) if output_json_path else _SCRIPT_DIR / "output.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data:
        raise ValueError("期望 JSON 根为 {batch_key: [ {...}, ... ] }")
    batch_key = next(iter(data.keys()))
    cases = data[batch_key]
    if not cases or not isinstance(cases[0], dict):
        raise ValueError("JSON 中无可用用例")
    case = cases[0]

    return run_single_test_case(case, batch_key=batch_key, output_json_path=out)


def run_auto_tests(input_json_path, output_json_path):
    """
    主函数：读取 JSON 文件，对每个用例执行自动化，更新并保存
    """
    # 1. 启动并获取应用对象
    atomacos.launchAppByBundleId(TRAE_BUNDLE_ID)
    time.sleep(4)   # 等待应用完全打开
    app = atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)
    if not app:
        raise RuntimeError("无法连接到 TRAE CN 应用，请检查 Bundle ID 和辅助功能权限")

    # 2. 读取测试用例
    with open(input_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 假设 JSON 根是一个对象，键为 batch name（如 "batch001"）
    batch_key = list(data.keys())[0] if data else None
    if not batch_key:
        raise ValueError("JSON 文件格式错误：缺少 batch 键")

    test_cases = data[batch_key]
    print(f"共加载 {len(test_cases)} 条测试用例")

    # 3. 逐个执行
    for idx, case in enumerate(test_cases, 1):
        print(f"\n====== 处理第 {idx} 条用例 ======")
        try:
            run_single_test_case(
                case,
                batch_key=batch_key,
                output_json_path=output_json_path,
            )
        except Exception as e:
            print(f"用例执行失败: {e}")
            # 标记失败信息
            case["日志轨迹"] = f"自动化执行异常: {str(e)}"

    # 4. 保存结果
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存至 {output_json_path}")

if __name__ == "__main__":


    import atomacos
    import pyautogui
    from locate_trae_ui import *

    atomacos.launchAppByBundleId("cn.trae.app")
    app = atomacos.getAppRefByBundleId("cn.trae.app")

    #
    # def rutest1():
    #     # 示例用法
    #     # run_auto_tests("batch001.json", "output.json")
    #     file="/Users/oce/Documents/TreaAi/gui-auto/prompts.json"
    #     run_single_test(file)
    #
    #     # 30batch,3lun
    #     dateID = datetime.date(datetime.now())
    #     dateID = str(dateID).replace("-", "")
    #     print("------1111-20260512---", dateID)
    #     batchID = "batch001"
    #
    #     # 创建文件目录
    #     FILE_DIR = "0512/batch001"
    #     FULL_DIR = os.path.join(BASE_WORK_DIR, FILE_DIR)
    #     os.makedirs(FULL_DIR, exist_ok=True)
    #
    #     # 打开基本tree目录文件
    #     open_trae(FULL_DIR)
    #     time.sleep(10)
    #
    #     # 1.读取提示词
    #     # test_prompt = read_prompt(banchid, roundid)
    #     # test_prompt = "11213213132132"
    #
    #     file = "/Users/oce/Documents/TreaAi/gui-auto/prompts.json"
    #     test_case = read_prompt_from_json(file)
    #     print(test_case, "------11111")
    #     test_prompt = test_case
    #
    #     # 2.找到输入框，定位输入框，输入内容
    #     input_prompt(test_prompt)
    #     # save_file(test_prompt)---暂时不需要了
    #
    #     # 3.发送输入
    #     time.sleep(1)
    #     pyautogui.press('enter', 2)
    #     time.sleep(0.2)
    #     pyautogui.press('enter', 2)
    #     print("已按回车发送")
    #     time.sleep(20.3)
    #
    #     # 4.双击solo coder获取session id
    #     # click_x, click_y = 264, 579
    #     # pyautogui.doubleClick(click_x, click_y)
    #     get_sessionID()
    #     time.sleep(1)
    #     # 5.滑动到最下方
    #     scroll_down()
    #     time.sleep(1)
    #     # 6.点击复制按钮，保存到csv
    #     get_log_file()