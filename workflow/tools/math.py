# math.py — intentionally empty.
#
# science_calculate_tool was removed: relied on a private WebSocket endpoint
#   ws://120.224.146.203:28083 with hardcoded auth keys.
# tora_calculate_tool was removed: relied on a private gateway
#   https://gateway.taichuai.cn/tora/tora
# add_calculator / subtraction_calculator were removed: trivially simple,
#   the CodeAct executor handles arithmetic directly.
#
# Mathematical computation is handled by the CodeAct sandbox executor, which
# can run arbitrary Python (numpy, scipy, sympy, etc.) without a dedicated tool.
