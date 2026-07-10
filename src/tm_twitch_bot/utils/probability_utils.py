from typing import List, Any, Union
import random


def weighted_random_choice(
    items: List[Any], weights: Union[List[float], List[int]]
) -> Any:
    if len(items) != len(weights):
        raise ValueError("Items and weights must have the same length.")
    if not items or not weights:
        raise ValueError("Items and weights cannot be empty.")
    return random.choices(items, weights=weights, k=1)[0]


if __name__ == "__main__":
    rarities = ["A賞", "B賞", "C賞", "D賞", "E賞", "F賞"]
    probabilities = [2, 3, 5, 10, 30, 50]
    results = random.choices(rarities, weights=probabilities, k=10000)
    count = {}
    for result in results:
        if result not in count:
            count[result] = 1
        else:
            count[result] += 1
    print(f"count: {count}")
