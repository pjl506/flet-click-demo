"""本地浏览器模式运行入口：复用 app/main.py（单一代码源）。

用法：
    python fletrun.py
"""
import os
import runpy

_HERE = os.path.dirname(os.path.abspath(__file__))

runpy.run_path(os.path.join(_HERE, "app", "main.py"), run_name="__main__")
