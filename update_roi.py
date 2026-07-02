import re

path = "/home/user/ai-trader/freqtrade/user_data/strategies/AI_AdaptiveStrategy.py"
with open(path) as f:
    content = f.read()

# Replace the ROI section
old_roi = """    minimal_roi = {
        "0": 0.03,
        "60": 0.02,
        "120": 0.01,
    }"""

new_roi = """    minimal_roi = {
        "0": 0.01,      # 1% — сразу выходим при малейшем плюсе
        "40": 0.008,    # 0.8% через 40 мин
        "80": 0.005,    # 0.5% через 80 мин
        "160": 0.002,   # 0.2% через 160 мин
    }"""

if old_roi in content:
    content = content.replace(old_roi, new_roi)
    with open(path, "w") as f:
        f.write(content)
    print("ROI updated successfully")
else:
    print("ERROR: Could not find old ROI pattern in file")
    # Debug: show what's around the ROI area
    if "minimal_roi" in content:
        idx = content.index("minimal_roi")
        print(f"Found minimal_roi at position {idx}")
        print(content[idx:idx+200])
