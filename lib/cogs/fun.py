import asyncio
import traceback
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


class Fun(commands.Cog, name="fun"):
    """Fun commands for staff and members, including voice channel tossing."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    VOICE_CHANNELS = (
        1006208134760632371,
        1014346606100889650,
    )

    @app_commands.checks.has_any_role(992669093545136189, 771099590032097343)
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.command(
        name="toss",
        description="Toss a user between voice channels to get their attention."
    )
    @app_commands.describe(
        member="User to toss between channels.",
        amount="Number of full cycles to move them through."
    )
    @app_commands.checks.has_permissions(ban_members=True)
    async def toss(
            self,
            itx: discord.Interaction,
            member: discord.Member,
            amount: app_commands.Range[int, 1, 10]
    ) -> None:
        """Move a member between predefined voice channels repeatedly."""
        channels = [itx.guild.get_channel(cid) for cid in self.VOICE_CHANNELS]
        if None in channels:
            await itx.response.send_message(
                "⚠️ One or more voice channels are invalid!",
                ephemeral=True
            )
            return

        if not member.voice:
            await itx.response.send_message(
                f"{member.display_name} is not in a voice channel!",
                ephemeral=True
            )
            return

        await itx.response.send_message(
            f"🌀 Tossing {member.display_name} around {amount} times! Hold on..."
        )

        original_channel = member.voice.channel

        try:
            for _ in range(amount):
                for channel in channels:
                    await member.move_to(channel)
                    await asyncio.sleep(1)

            await member.move_to(original_channel)

        except discord.Forbidden:
            await itx.followup.send(
                "❌ You don't have permissions to move members!",
                ephemeral=True
            )
        except discord.HTTPException as e:
            traceback.print_exc()
            await itx.followup.send(
                f"⚠️ Failed to move user: {e}",
                ephemeral=True
            )

    @app_commands.command(
        name="roll",
        description="Roll a number of dice."
    )
    @app_commands.describe(
        count="Number of dice (1-100)",
        sides="Number of sides on each die (100 max)"
    )
    async def roll(
            self,
            itx: discord.Interaction,
            count: app_commands.Range[int, 1, 100],
            sides: app_commands.Range[int, 2, 100],
            member: discord.Member = None
    ) -> None:
        """Roll dice and display results"""

        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)

        embed = discord.Embed(
            title="🎲 Dice Roll Results",
            color=discord.Color.blue()
        )

        embed.set_author(name=f"{itx.user.display_name}'s Roll", icon_url=itx.user.display_avatar.url)

        embed.add_field(
            name="Dice Rolled",
            value=f"{count}d{sides}",
            inline=True
        )

        embed.add_field(
            name="Total",
            value=str(total),
            inline=True
        )

        if count <= 20:
            roll_display = ", ".join(
                f"**{roll}**" if roll == sides else str(roll)
                for roll in rolls
            )
            embed.add_field(
                name="Individual Rolls",
                value=roll_display,
                inline=False
            )
        else:
            embed.add_field(
                name="Note",
                value="Too many dice to show individual results!",
                inline=False
            )

        if count == 1 and rolls[0] == sides:
            embed.set_footer(text="Nat 20! Critical success! 🎉")
            embed.color = discord.Color.green()
        elif count == 1 and rolls[0] == 1:
            embed.set_footer(text="Critical failure! 💀")
            embed.color = discord.Color.red()
        elif all(r == sides for r in rolls):
            embed.set_footer(text="All max rolls! Incredible! 🤯")
            embed.color = discord.Color.gold()
        elif all(r == 1 for r in rolls):
            embed.set_footer(text="All ones... ouch. 😬")
            embed.color = discord.Color.dark_red()

        mention = f" for {member.mention}" if member else ""

        await itx.response.send_message(
            content=f"{itx.user.mention} rolled {count}d{sides}{mention}!",
            embed=embed
        )

    @app_commands.checks.cooldown(1, 300.0, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.command(
        name="ping",
        description="Get their attention!"
    )
    @app_commands.describe(
        member="Who's ignoring you?",
        count="Number of +1's"
    )
    async def ping(
            self,
            itx: discord.Interaction,
            member: discord.Member,
            count: app_commands.Range[int, 1, 5]
    ) -> None:
        """Ping a player"""

        try:
            await itx.response.send_message(
                f"Pinging {member.mention} {count} times!",
                allowed_mentions=discord.AllowedMentions(users=True)
            )

            for i in range(count):
                await itx.followup.send(
                    content=f"{member.mention} Ping #{i + 1}!",
                    allowed_mentions=discord.AllowedMentions(users=True)
                )
                await asyncio.sleep(1)

        except discord.Forbidden:
            await itx.response.send_message(
                "You don't have permission to mention users or send messages here!",
                ephemeral=True
            )
        except discord.HTTPException as e:
            await itx.response.send_message(
                f"Something went wrong while pinging: {e}",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(
        Fun(bot),
        guilds=[
            discord.Object(id=771099589713199145),
            discord.Object(id=601677205445279744)
        ]
    )
