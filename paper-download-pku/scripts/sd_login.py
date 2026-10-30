#!/usr/bin/env python
"""ScienceDirect 机构登录（北大 CARSI），登录态写入持久化 profile。

用法：python sd_login.py [--profile <目录>]
等价于：python fetch_papers.py sd-login
"""

import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv = [sys.argv[0], "sd-login"] + sys.argv[1:]
runpy.run_path(os.path.join(HERE, "fetch_papers.py"), run_name="__main__")
