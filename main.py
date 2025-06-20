#!/usr/bin/python3
from secrets import TOKEN

import discord
from discord.ext import commands
import os
import sys
import time
import datetime
import traceback
import aiohttp
from discord import Interaction, app_commands
from discord.app_commands import AppCommandError

# Does not allow bot to start without config file
if not os.path.isfile("config.py"):
    sys.exit("'config.py' not found! Please add it and restart the bot")
else:
    import config


class GeneralBot(commands.Bot):
    """
    General bot for HeroCraft.
    """

    def __init__(self):
        super().__init__(
            command_prefix=config.BOT_PREFIX,
            intents=discord.Intents.all())

        self.session = None
        self.initial_extensions = []

        for file in os.listdir("lib/cogs"):
            if file.endswith(".py"):
                extension = file[:-3]
                try:
                    self.initial_extensions.append(f"lib.cogs.{extension}")
                    print(f"Added extension: '{extension}'")
                except Exception as e:
                    exception = f"{type(e).__name__}: {e}"
                    print(f"Failed to load extension {extension}\n{exception}")
                    pass

        print(f'Full List: {self.initial_extensions}')

    async def setup_hook(self):
        for ext in self.initial_extensions:
            await self.load_extension(ext)
        # self.session = aiohttp.ClientSession()
        print(f'Syncing Guilds -')

    async def close(self):
        await super().close()
        # await self.session.close()

    async def on_ready(self):
        print(f'GMT Local Time: {time.ctime(time.time())}')
        print(f'Successfully logged in as {self.user} -- Awaiting Commands')

    async def on_connect(self):
        await self.change_presence(status=discord.Status.online, activity=discord.Game(config.GAME_STATUS))
        print(f"\nBot Connected Successfully... Logging in ---")


bot = GeneralBot()


# 992669093545136189
@bot.command(name='gsync')
async def _gsync(ctx):
        guilds = [601677205445279744, 771099589713199145]
        synced_guilds = []
        for g in guilds:
            try:
                guild = await bot.get_guild(g)
                synced_guilds.append(f"{guild.name}\n{g}")
                print(guild.get_user(int(ctx.guild.owner.id)))
                await bot.tree.sync(guild=discord.Object(id=g))
                print(f"{g} was synced....")
            except Exception as err:
                print(f"Skipped {g} for error: {err}")
                continue
        print(f"Guilds have been synced")



# Error handling in chat
async def error_embed(interaction: Interaction, error: AppCommandError, message: str):
    embed = discord.Embed(
        title="Error!",
        description=f"{message}",
        color=config.error
    )
    embed.add_field(name='Error: ', value=f'{error}')
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.error
async def on_app_command_error(itx: Interaction, error: AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        time_remaining = str(datetime.timedelta(
            seconds=int(error.retry_after)))
        await error_embed(itx, error, f'Please wait `{time_remaining}` to execute this command again.')
    elif isinstance(error, app_commands.MissingRole):
        await error_embed(itx, error, f'You do not have permission to run this command!')
    else:
        await error_embed(itx, error, f'This command has raised an error!')


if __name__ == '__main__':
    bot.run(TOKEN)
