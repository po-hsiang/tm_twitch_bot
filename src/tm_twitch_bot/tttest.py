"""
10 等可進行一轉：
劍士、服事、魔法師、商人、弓箭手、盜賊、跆拳、忍者、槍手、超級初學者、海盜

15 等可進行二轉：
騎士、十字軍、狂戰士、祭司、僧侶、武道家、巫師、賢者、鐵匠、煉金術師、獵人、弩弓手、吟遊詩人、舞孃、刺客、俠客、流氓

未來還會擴充三轉、四轉等等
"""

raw_data = [
    ["一轉", "二轉"],
    ["10", "15"],
    ["劍士", "騎士"],
    ["服事", "十字軍"],
    ["魔法師", "狂 戰士"],
    ["商人", "祭司"],
    ["弓箭手", "僧侶"],
    ["盜賊", "武道家"],
    ["跆拳", "巫師"],
    ["忍者", "賢者"],
    ["槍手", "鐵匠"],
    ["超 級初學者", "煉金術師"],
    ["海盜", "獵人"],
    ["", "弩弓手"],
    ["", "吟遊詩人"],
    ["", "舞孃"],
    ["", "刺客"],
    ["", "俠客"],
    ["", " 流氓"],
]


def parse_jobs_sheet(raw_data: list[list[str]]) -> dict[int, dict]:
    """
    raw_data 來自 google_sheets_client.get_sheet_data()
    第一列 → 中文序，第二列 → 等級門檻，其餘列 → 各職業
    """
    if len(raw_data) < 3:
        raise ValueError("資料格式不足，無法解析")

    stages = raw_data[0]
    levels_line = raw_data[1]  # ['10', '15', ...]
    job_rows = raw_data[2:]  # 之後每列都是職業
    job_config: dict[int, dict] = {}
    for idx, lvl in enumerate(levels_line):
        stage_name = stages[idx]
        jobs = [row[idx].strip() for row in job_rows if row[idx].strip()]
        job_config[lvl] = {"stage": stage_name, "jobs": jobs}
    return job_config


def exp_between(a: int, b: int) -> int:
    """回傳從等級 a 升到 b 所需的總經驗值（不含 b->b+1）。"""
    if b <= a:
        return 0
    return 10 * (a + b - 1) * (b - a) // 2


if __name__ == "__main__":
    # low = 15
    # high = 20
    # exp = exp_between(low, high)
    # print(f"{low} ~ {high}: {exp}")
    job_config = parse_jobs_sheet(raw_data)
    print(f"job_config: {job_config}")
