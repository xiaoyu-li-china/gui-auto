#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
轻量示例：在脚本所在目录下创建「月日/batch_id」目录，并用 Trae CN 打开该路径。

打开逻辑委托给 ``trae_auto_runner.run_open_trae_workspace_subprocess``（默认先 ``open -a`` 再视情况 ``-b``，与 111 一致）。
完整自动化请使用：``python3.11 trae_auto_runner.py --help``。
"""
from datetime import datetime
from pathlib import Path


def create_workspace_dir(batch_id="batch001", base_work_dir=None):
    """在 ``base_work_dir/月日/batch_id`` 下创建目录，返回绝对路径字符串。"""
    root = Path(base_work_dir or Path(__file__).resolve().parent)
    today_str = datetime.now().strftime("%m%d")
    full_dir = (root / today_str / batch_id).resolve()
    from trae_auto_runner import _makedirs_exists_ok

    _makedirs_exists_ok(full_dir)
    return str(full_dir)


def open_trae(workspace_path):
    """
    用 Trae CN 打开已有目录（目录须已存在，否则 ``FileNotFoundError``）。
    底层使用 ``run_open_trae_workspace_subprocess``（与 trae_auto_runner 打开工作区逻辑一致）。
    """
    p = Path(workspace_path).expanduser().resolve()
    if not p.is_dir():
        raise FileNotFoundError(workspace_path)

    import atomacos
    import time

    from trae_auto_runner import TRAE_BUNDLE_ID, run_open_trae_workspace_subprocess

    run_open_trae_workspace_subprocess(
        p,
        new_instance=False,
        bundle_id=TRAE_BUNDLE_ID,
        log_prefix="[111.py]",
    )
    time.sleep(3)
    return atomacos.getAppRefByBundleId(TRAE_BUNDLE_ID)


if __name__ == "__main__":
    work_dir = create_workspace_dir("batch0012")
    app = open_trae(work_dir)
    print(f"已打开 Trae CN，工作目录: {work_dir}, app对象: {app}")
