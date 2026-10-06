from livekit.agents.llm import function_tool

@function_tool(
    name="roll_dice",
    description="Roll a die with the given number of sides. Use when the user asks for a dice roll or random number.",
)
async def roll_dice(sides: int = 6) -> str:
    import random
    try:
        n = int(sides)
        if n < 2:
            return "The die needs at least 2 sides."
        return "Rolled a %d-sided die: %d" % (n, random.randint(1, n))
    except Exception as e:
        return "Could not roll the die: %s" % e