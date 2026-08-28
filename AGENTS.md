# DiscoAS 项目规则

- 统一使用项目解释器：`.\.venv\Scripts\python.exe`（Python 3.12.9），不要使用裸 `python`。
- 如果沙箱内无法运行项目解释器，先申请该命令的 `require_escalated` 权限再验证；不要直接判断 Python 不存在或 `.venv` 损坏，也不要擅自重建环境。
- 调试启动：`.\.venv\Scripts\python.exe main.py`；正常启动使用 `start.cmd`。
- 运行测试：`.\.venv\Scripts\python.exe -m pytest -q --basetemp .\.test-tmp`。
- 静态检查：`.\.venv\Scripts\python.exe -m ruff check .`。
- 测试结果只报告当次实际输出。
