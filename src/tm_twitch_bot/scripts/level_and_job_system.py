from tm_twitch_bot.svc_client.google_sheets import google_sheets_client


RAW_JOB_DATA = google_sheets_client.get_sheet_data("轉職表")


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
        job_config[int(lvl)] = {"stage": stage_name, "jobs": jobs}
    return job_config


JOB_CONFIG = parse_jobs_sheet(RAW_JOB_DATA)


# def experience_to_next_level(level: int) -> int:
#     return level * 10


# def calculate_level_and_exp(
#     current_level: int, current_exp: int, gained_exp: int
# ) -> tuple[int, int]:

#     total_exp = current_exp + gained_exp
#     level = current_level

#     while total_exp >= experience_to_next_level(level):
#         total_exp -= experience_to_next_level(level)
#         level += 1

#     return level, total_exp


if __name__ == "__main__":
    # test_inputs = [(1, 0, 1), (1, 9, 1), (1, 0, 10), (1, 5, 10), (3, 25, 7)]

    # for current_level, current_exp, gained_exp in test_inputs:
    #     print(
    #         f"\n\nTesting with Current Level: {current_level}, Current EXP: {current_exp}, Gained EXP: {gained_exp}"
    #     )
    #     new_level, remaining_exp = calculate_level_and_exp(
    #         current_level, current_exp, gained_exp
    #     )
    #     print(f"New Level: {new_level}, Remaining EXP: {remaining_exp}")
    print(f"RAW_JOB_DATA: {RAW_JOB_DATA}")
    print(f"JOB_CONFIG: {JOB_CONFIG}")
