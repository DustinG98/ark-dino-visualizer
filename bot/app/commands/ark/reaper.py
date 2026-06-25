import discord
from discord import app_commands, Interaction


def register_reaper(ark_group: app_commands.Group) -> None:
    @ark_group.command(name="reaper", description="Calculate Reaper level from queen and player levels.")
    @app_commands.describe(
        queen_level="Reaper Queen's level",
        player_level="Player's character level",
        extra_levels="Did the pregnancy receive max XP bonus?",
    )
    async def reaper_cmd(
        interaction: Interaction,
        queen_level: int,
        player_level: int,
        extra_levels: bool,
    ):
        base_level = int(queen_level * ((player_level + 100) / 250))
        final_level = base_level + (75 if extra_levels else 0)

        if final_level >= 500:
            title = "Reaper Level Calculation"
            desc = (
                f"**Base level:** {base_level}\n"
                f"**XP bonus:** +{75 if extra_levels else 0}\n"
                f"**Final level:** {final_level}\n\n"
                "Exceptional result — this is a powerful Reaper!"
            )
            color = discord.Color.dark_purple()
        elif final_level >= 300:
            title = "Reaper Level Calculation"
            desc = (
                f"**Base level:** {base_level}\n"
                f"**XP bonus:** +{75 if extra_levels else 0}\n"
                f"**Final level:** {final_level}\n\n"
                "Solid Reaper. Worth the grind."
            )
            color = discord.Color.blue()
        else:
            title = "Reaper Level Calculation"
            desc = (
                f"**Base level:** {base_level}\n"
                f"**XP bonus:** +{75 if extra_levels else 0}\n"
                f"**Final level:** {final_level}\n\n"
                "Low yield. Consider higher queen/player levels before breeding."
            )
            color = discord.Color.orange()

        embed = discord.Embed(title=title, description=desc, color=color)
        await interaction.response.send_message(embed=embed)
