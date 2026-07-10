from tm_twitch_bot.utils.probability_utils import weighted_random_choice

ITEMS = ["tigerm24Black", "tigerm24Staring", "tigerm24Rainbow", "tigerm24Sharingan"]
WEIGHTS = [800, 180, 18, 2]
REWARD_MAP = {
    "tigerm24Staring": 3,
    "tigerm24Rainbow": 40,
    "tigerm24Sharingan": 370,
}
PULL_COST = 20


def gacha(*args, **kwargs) -> str:
    char = kwargs.get("char")
    if char.gold < PULL_COST:
        return f"不足 {PULL_COST} Gold 無法抽卡，目前才 {char.gold} Gold 💸 "

    char.gold -= PULL_COST  # 統一先扣錢

    pulls = []
    reward = 0

    # TODO 暫時將 10 抽保底機制關起來
    # black_count = 0
    for _ in range(10):
        result = weighted_random_choice(ITEMS, WEIGHTS)
        # if result == "tigerm24Black":
        # black_count += 1
        pulls.append(result)
        reward += REWARD_MAP.get(result, 0)

    # 十抽全黑 → 保底
    # if black_count == 10:
    #     pulls[-1] = "tigerm24Staring"

    pulls_text = " ".join(pulls)

    if reward > 0:
        char.gain_gold(reward)  # 有贏才加錢
        final_output = f"{pulls_text} 恭喜獲得 {reward} Gold tigerm24High"
    else:
        final_output = f"{pulls_text} 什麼都沒有 tigerm2488"

    return final_output


if __name__ == "__main__":
    w = 800
    x = 180
    y = 18
    z = 2
    A = 3
    B = 40
    C = 370
    answer = x * A + y * B + z * C
    print(answer)
