
import random
from datetime import datetime, timedelta
import asyncio
import json
from pathlib import Path

import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Select

from lib.cogs.economy import EconomyUtils


class BetButton(Button):
    def __init__(self, color, label, emoji, style):
        super().__init__(label=label, emoji=emoji, style=style)
        self.color = color

    async def callback(self, interaction):
        await interaction.response.defer()

        view = BetAmountView(self.color)
        await interaction.followup.send(
            f"Select your bet amount for {self.color.capitalize()}",
            view=view,
            ephemeral=True
        )


class BetAmountView(View):
    def __init__(self, color):
        super().__init__(timeout=60)
        self.color = color
        self.add_item(BetAmountSelect(color))


class BetAmountSelect(discord.ui.Select):
    def __init__(self, color):
        options = [
            discord.SelectOption(label="5 coins", value="5"),
            discord.SelectOption(label="25 coins", value="25"),
            discord.SelectOption(label="100 coins", value="100"),
            discord.SelectOption(label="500 coins", value="500"),
            discord.SelectOption(label="1000 coins", value="1000"),
        ]
        super().__init__(
            placeholder="Select your bet amount...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.color = color

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await interaction.delete_original_response()
        except discord.NotFound:
            pass
        amount = int(self.values[0])
        cog = interaction.client.get_cog("Roulette")
        economy = EconomyUtils()

        balance = economy.get_balance(interaction.user.id)
        if balance < amount:
            error_msg = await interaction.followup.send(
                f"❌ You don't have enough coins! Balance: {balance}",
                ephemeral=True
            )
            await asyncio.sleep(5)
            await error_msg.delete()
            return

        cog.bets[interaction.user.id] = (amount, self.color)
        economy.update_balance(interaction.user.id, -amount)
        cog.force_update = True

        confirm_msg = await interaction.followup.send(
            f"✅ Bet placed! {amount} coins on {self.color.capitalize()}",
            ephemeral=True
        )
        await asyncio.sleep(5)
        await confirm_msg.delete()


class RouletteView(View):
    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(BetButton("yellow", "Yellow", "🟨", discord.ButtonStyle.secondary))
        self.add_item(BetButton("green", "Green", "🟩", discord.ButtonStyle.secondary))
        self.add_item(BetButton("blue", "Blue", "🟦", discord.ButtonStyle.secondary))
        self.add_item(BetButton("pink", "Pink", "🟪", discord.ButtonStyle.secondary))
        self.add_item(BetButton("red", "Red", "🟥", discord.ButtonStyle.secondary))


class Roulette(commands.Cog):
    def __init__(self, bot: commands.Bot, economy_utils):
        self.bot = bot
        self.economy = economy_utils
        self.logs_dir = Path("data/casino_logs/")
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.wheel = [
            *[("yellow", 1) for _ in range(12)],
            *[("green", 3) for _ in range(6)],
            *[("blue", 5) for _ in range(4)],
            *[("pink", 10) for _ in range(2)],
            ("red", 20)
        ]
        self.current_winner = None
        self.bets = {}
        self.message = None
        self.game_thread_id = 1372248900311847032
        self.announcement_channel_id = 1372248900311847032
        self.next_spin_time = None
        self.spin_lock = asyncio.Lock()
        self.is_running = False
        self.bot.add_listener(self.on_message, 'on_message')
        self.roulette_task = self._create_task()
        self._message_lock = asyncio.Lock()
        self._countdown_lock = asyncio.Lock()
        self.spinning_until = None
        self._last_countdown = None

    def cog_unload(self):
        if self.roulette_task.is_running():
            self.roulette_task.cancel()
        self.bot.remove_listener(self.on_message, 'on_message')

    async def on_message(self, message):
        """Handle start/stop commands from thread"""
        if message.channel.id != self.game_thread_id:
            return

        if message.author == self.bot.user:
            return

        if not isinstance(message.author, discord.Member):
            return

        if not message.author.guild_permissions.manage_channels:
            return

        content = message.content.lower().strip()

        try:
            if content not in ('start', 'stop'):
                await message.delete()
            await message.delete()
        except discord.NotFound:
            self.message = None
            await self.initialize_game_message()
        except discord.HTTPException as e:
            if e.status == 429:
                await asyncio.sleep(e.reset_after or 10.0)

        if content == 'stop' and self.is_running:
            self.is_running = False
            if self.roulette_task.is_running():
                self.roulette_task.cancel()
            if self.message:
                await self.message.delete()

        elif content == 'start' and not self.is_running:
            self.is_running = True
            if not self.roulette_task.is_running():
                await self.initialize_game_message()
                self.roulette_task.start()

    def _save_roulette_log(self, log_entry):
        """Save roulette results to JSON log file"""
        try:
            # Create date-based filename
            today = datetime.now().strftime("%Y-%m-%d")
            log_file = self.logs_dir / f"roulette_{today}.json"

            # Load existing logs or create new list
            if log_file.exists():
                with open(log_file, "r") as f:
                    logs = json.load(f)
            else:
                logs = []

            # Append new entry
            logs.append(log_entry)

            # Save back to file
            with open(log_file, "w") as f:
                json.dump(logs, f, indent=2)

        except Exception as e:
            print(f"Error saving roulette log: {e}")

    def _create_task(self):
        @tasks.loop(seconds=10.0)
        async def task_loop():
            if not self.is_running:
                return

            now = datetime.now()

            if self.next_spin_time is None:
                self.schedule_next_spin(now)

            if now >= self.next_spin_time and not self.spin_lock.locked():
                async with self.spin_lock:
                    await self.process_spin()

            await self.safe_update_display()

        @task_loop.before_loop
        async def before_task():
            await self.bot.wait_until_ready()
            if not self.is_running:
                return
            if not self.message:
                await self.initialize_game_message()

        @task_loop.after_loop
        async def after_task():
            self.is_running = False

        return task_loop

    async def initialize_game_message(self):
        """Create initial game message in thread"""
        async with self._message_lock:
            if self.message is None:
                game_thread = self.bot.get_channel(self.game_thread_id)
                if game_thread:
                    try:
                        async for msg in game_thread.history(limit=5):
                            if msg.author == self.bot.user and msg.embeds:
                                self.message = msg
                                return

                        self.message = await game_thread.send(
                            embed=self.create_embed(),
                            view=RouletteView()
                        )
                    except discord.HTTPException:
                        pass

    async def safe_update_display(self):
        try:
            if self.message is None:
                await self.initialize_game_message()
                return

            now = datetime.now()
            time_left = max(0, (self.next_spin_time - now).total_seconds())
            spinning_active = self.spinning_until and now < self.spinning_until

            phase_text = "Countdown"

            if time_left == 30:
                phase_text = "Starting Soon..."
                countdown_text = " "
            elif spinning_active:
                phase_text = "Spinning!"
                countdown_text = "🕐 Please Wait..."
            else:
                segments = 3
                filled = min(segments, int(time_left // 10))
                countdown_bar = "▰" * filled + "▱" * (segments - filled)
                countdown_text = f"Next spin in {'<10' if int(time_left) < 10 else int(time_left)}s\n{countdown_bar}"

            embed = self.create_embed()
            embed.set_field_at(0, name=phase_text, value=countdown_text, inline=False)

            view = RouletteView()
            if spinning_active:
                for item in view.children:
                    item.disabled = True

            await self.message.edit(embed=embed, view=view)

        except discord.NotFound:
            self.message = None
            await self.initialize_game_message()
        except discord.HTTPException as e:
            if e.status == 429:
                await asyncio.sleep(e.reset_after or 10.0)

    async def process_spin(self):
        """Handle the spin sequence (10 seconds) and schedule next spin"""
        async with self._countdown_lock:
            current_bets = self.bets.copy()
            self.bets.clear()
            self.current_winner = None
            self.spinning_until = datetime.now() + timedelta(seconds=10)
            await self.safe_update_display()

        await asyncio.sleep(10)

        self.current_winner = random.choice(self.wheel)
        await self._process_results_async(current_bets)

        self.schedule_next_spin(datetime.now())
        await self.safe_update_display()

    async def _process_results_async(self, current_bets):
        """Background processing of results"""
        try:
            announcement_channel = self.bot.get_channel(self.announcement_channel_id)
            if not announcement_channel or not current_bets:
                return

            color, multiplier = self.current_winner
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "winning_color": color,
                "multiplier": multiplier,
                "winners": [],
                "losers": []
            }
            winners = []
            losers = []

            for user_id, (amount, bet_color) in current_bets.items():
                user = self.bot.get_user(user_id)
                if not user:
                    continue

                if bet_color == color:
                    payout = amount + (amount * multiplier)
                    winners.append((user, amount, payout))
                    self.economy.update_balance(user_id, payout)
                    log_entry["winners"].append({
                        "user_id": user_id,
                        "username": str(user),
                        "bet": amount,
                        "bet_color": bet_color,
                        "payout": payout
                    })
                else:
                    losers.append((user, amount))
                    log_entry["losers"].append({
                        "user_id": user_id,
                        "username": str(user),
                        "bet": amount,
                        "bet_color": bet_color
                    })

            self._save_roulette_log(log_entry)

            embed = discord.Embed(
                title=f"🎰 Roulette Results: {color.capitalize()} (x{multiplier})",
                color=self.get_color_value(color)
            )

            if winners or losers:
                print(f"\n=== ROULETTE RESULTS [{color.upper()} x{multiplier}] ===")
            if winners:
                winner_text = "\n".join(f"🎉 {user.mention} won {payout} (bet: {amount})"
                                        for user, amount, payout in winners)
                embed.add_field(name="Winners", value=winner_text, inline=False)
                for user, amount, payout in winners:
                    print(f"🏆 WINNER: {user} (ID: {user.id})")
                    print(f"   Bet: {amount} → Won: {payout} (Net +{payout - amount})")
                    print(f"   Color: {color} | Multiplier: x{multiplier}\n")

            if losers:
                loser_text = "\n".join(f"💸 {user.mention} lost {amount}"
                                       for user, amount in losers)
                embed.add_field(name="Losers", value=loser_text, inline=False)
                for user, amount in losers:
                    print(f"💥 LOSER: {user} (ID: {user.id})")
                    print(f"   Lost: {amount} on {bet_color}\n")

            msg = await announcement_channel.send(embed=embed)
            await asyncio.sleep(10)
            await msg.delete()

        except discord.HTTPException as e:
            if e.status == 429:
                await asyncio.sleep(e.reset_after or 5.0)
                await self._process_results_async(current_bets)

    def schedule_next_spin(self, after: datetime):
        self.next_spin_time = after + timedelta(seconds=30)

    def create_embed(self):
        embed = discord.Embed(
            title="🎰 Casino Roulette 🎰",
            description="Place your bets using the buttons below!",
            color=self.get_color_value(self.current_winner[0]) if self.current_winner else discord.Color.gold()
        )

        embed.add_field(
            name="Countdown",
            value="Next spin in 30s\n▰▰▰",
            inline=False
        )

        if self.current_winner:
            color_name, multiplier = self.current_winner
            embed.add_field(
                name="Last Winner",
                value=f"**{color_name.capitalize()}** (x{multiplier})",
                inline=False
            )

        embed.add_field(
            name="Wheel Odds",
            value=(
                "🟨 Yellow (1x) - 12/25 | 48%\n"
                "🟩 Green (3x) - 6/25 | 24%\n"
                "🟦 Blue (5x) - 4/25 | 16%\n"
                "🟪 Pink (10x) - 2/25 | 8%\n"
                "🟥 Red (20x) - 1/25 | 4%"
            ),
            inline=False
        )

        if self.bets:
            bet_info = [
                f"{self.bot.get_user(user_id).display_name}: {amount} on {color}"
                for user_id, (amount, color) in self.bets.items()
                if self.bot.get_user(user_id)
            ]
            if bet_info:
                embed.add_field(
                    name="Current Bets",
                    value="\n".join(bet_info),
                    inline=False
                )

        return embed

    def get_color_value(self, color):
        return {
            "yellow": discord.Color.yellow(),
            "green": discord.Color.green(),
            "blue": discord.Color.blue(),
            "pink": discord.Color.magenta(),
            "red": discord.Color.red()
        }.get(color, discord.Color.gold())


async def setup(bot: commands.Bot):
    economy_utils = EconomyUtils()
    await bot.add_cog(
        Roulette(bot, economy_utils),
        guilds=[
            discord.Object(id=771099589713199145),
            discord.Object(id=601677205445279744)
        ]
    )
