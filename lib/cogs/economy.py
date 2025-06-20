import os
import json
import asyncio
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks


class EconomyUtils:
    def __init__(self):
        self.members_dir = Path(__file__).parent.parent / "members"
        self.members_dir.mkdir(exist_ok=True)

    def _get_member_path(self, user_id):
        return self.members_dir / f"{user_id}.json"

    def get_member_data(self, user_id):
        """Returns {balance, last_reward} or creates new file"""
        member_file = self._get_member_path(user_id)
        default_data = {"balance": 0, "last_reward": 0}

        try:
            if member_file.exists():
                with open(member_file, 'r') as f:
                    return {**default_data, **json.load(f)}
            return default_data
        except (json.JSONDecodeError, IOError):
            return default_data

    def get_balance(self, user_id):
        member_file = self._get_member_path(user_id)
        try:
            if member_file.exists():
                with open(member_file, 'r') as f:
                    return json.load(f).get('balance', 0)
            return 0
        except json.JSONDecodeError:
            return 0

    def update_balance(self, user_id, amount):
        """Updates balance AND last_reward timestamp"""
        data = self.get_member_data(user_id)
        data["balance"] = max(0, data["balance"] + amount)
        data["last_reward"] = time.time()

        with open(self._get_member_path(user_id), 'w') as f:
            json.dump(data, f)
        return data["balance"]


class Economy(commands.Cog, name="economy"):
    """Fun commands for staff and members, including voice channel tossing."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.economy = EconomyUtils()
        # self.members_dir = Path(__file__).parent.parent / "members"
        # self.members_dir.mkdir(exist_ok=True)
        self.cooldown_seconds = 15 * 60
        self.message_reward = 10
        self.voice_reward = 1
        self.reward_channels = {
            640022556337766425: (1, 120),  # (coins per 5 minutes, max daily minutes)
            1006208134760632371: (1, 60),
            1014346606100889650: (2, 180)
        }
        self.voice_timers = {}
        self.daily_usage = {}
        self.reward_interval = 300  # Rewarded for being in voice this long
        self.voice_check.start()

    def cog_unload(self):
        """Cleanup task when user leaves voice channel"""
        self.voice_check.cancel()

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handles message rewards with cooldown"""
        if message.author.bot or not message.guild:
            return

        user_id = str(message.author.id)
        data = self.economy.get_member_data(user_id)
        current_time = time.time()

        if current_time - data["last_reward"] < self.cooldown_seconds:
            remaining = self.cooldown_seconds - (current_time - data["last_reward"])
            print(f"{message.author} needs to wait {int(remaining // 60)}m {int(remaining % 60)}s")
            return

        new_balance = self.economy.update_balance(user_id, self.message_reward)
        print(f"Rewarded {message.author}. New balance: {new_balance}")

    async def check_voice_activity(self, user_id, guild_id):
        """Check if a user is actively participating in voice"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False

        member = guild.get_member(int(user_id))
        if not member or not member.voice:
            return False

        voice_state = member.voice
        return (
                (not voice_state.self_mute and not voice_state.self_deaf) or
                voice_state.self_video or
                voice_state.self_stream
        )

    @tasks.loop(minutes=5)
    async def voice_check(self):
        now = datetime.now(timezone.utc)
        today = now.date()

        for user_id, (start_time, channel_id, last_activity, guild_id) in list(self.voice_timers.items()):
            guild = self.bot.get_guild(guild_id)
            if not guild:
                del self.voice_timers[user_id]
                continue

            member = guild.get_member(int(user_id))
            if not member:
                del self.voice_timers[user_id]
                continue

            is_active = await self.check_voice_activity(user_id, guild_id)
            current_voice = getattr(member.voice, "channel", None)

            if (not is_active and (now - last_activity) > timedelta(minutes=10)) or (
                    current_voice and current_voice.id != channel_id):
                del self.voice_timers[user_id]
                continue

            daily_data = self.daily_usage.get(user_id, {}).get(today, {"minutes": 0, "coins": 0})
            max_daily = self.reward_channels[channel_id][1]

            if daily_data["minutes"] >= max_daily:
                del self.voice_timers[user_id]
                continue

            reward, _ = self.reward_channels[channel_id]
            duration = (now - start_time).total_seconds() / 60

            if duration >= 5:
                if user_id not in self.daily_usage:
                    self.daily_usage[user_id] = {}
                if today not in self.daily_usage[user_id]:
                    self.daily_usage[user_id][today] = {"minutes": 0, "coins": 0}

                self.daily_usage[user_id][today]["minutes"] += 5
                self.daily_usage[user_id][today]["coins"] += reward
                self.economy.update_balance(user_id, reward)
                self.voice_timers[user_id] = (now, channel_id, now, guild_id)

                print(f"Voice reward: {member.display_name} (ID: {user_id}) +{reward} coins in channel {channel_id}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        user_id = str(member.id)
        guild_id = member.guild.id
        now = datetime.now(timezone.utc)
        today = now.date()

        if before.channel and before.channel.id in self.reward_channels:
            if user_id in self.voice_timers:
                start_time, channel_id, _, _ = self.voice_timers[user_id]
                duration = (now - start_time).total_seconds() / 60

                if await self.check_voice_activity(user_id, guild_id) and duration >= 1:
                    reward_config = self.reward_channels[channel_id]
                    daily_usage = self.daily_usage.get(user_id, {}).get(today, {"minutes": 0, "coins": 0})

                    reward = min(
                        int(duration // 5) * reward_config[0],
                        reward_config[1] * reward_config[0] - daily_usage["coins"]
                    )

                    if reward > 0:
                        self.economy.update_balance(user_id, reward)
                        if user_id not in self.daily_usage:
                            self.daily_usage[user_id] = {}
                        if today not in self.daily_usage[user_id]:
                            self.daily_usage[user_id][today] = {"minutes": 0, "coins": 0}
                        self.daily_usage[user_id][today]["coins"] += reward
                        self.daily_usage[user_id][today]["minutes"] += int(duration)
                        print(f"Final voice reward: {member.display_name} +{reward} coins")
                del self.voice_timers[user_id]

        if after.channel and after.channel.id in self.reward_channels:
            reward_config = self.reward_channels[after.channel.id]
            daily_usage = self.daily_usage.get(user_id, {}).get(today, {"minutes": 0, "coins": 0})

            if daily_usage["minutes"] < reward_config[1]:
                self.voice_timers[user_id] = (now, after.channel.id, now, guild_id)
                print(f"Tracking voice time for {member.display_name} in {after.channel.name}")

    # Commands --

    @app_commands.command(name="voicetime", description="Check your current voice earnings")
    async def voicetime(self, interaction: discord.Interaction):
        """Check your daily voice earnings"""
        user_id = str(interaction.user.id)
        today = datetime.now(timezone.utc).date()
        stats = self.daily_usage.get(user_id, {}).get(today, {"minutes": 0, "coins": 0})

        embed = discord.Embed(
            title="🎧 Voice Activity Stats",
            color=0x3498db
        )

        embed.add_field(name="Today's Earnings", value=f"{stats['coins']} coins", inline=True)
        embed.add_field(name="Minutes Used", value=f"{stats['minutes']}/120 mins", inline=True)
        embed.add_field(name="Active Now", value="✅" if user_id in self.voice_timers else "❌", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="cooldown", description="Check your reward cooldown status")
    async def cooldown_check(self, interaction: discord.Interaction):
        """Check when you can earn coins again"""
        data = self.economy.get_member_data(str(interaction.user.id))
        remaining = max(0, int(self.cooldown_seconds - (time.time() - data["last_reward"])))

        if remaining > 0:
            await interaction.response.send_message(
                f"⏳ You can earn coins again in {int(remaining // 60)}m {int(remaining % 60)}s",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "✅ You can earn coins right now! Send a message!",
                ephemeral=True
            )

    @app_commands.command(name='balance')
    async def balance(self, interaction: discord.Interaction, user: discord.Member = None):
        """Check coin balance"""
        target = user or interaction.user
        balance = self.economy.get_balance(str(target.id))

        embed = discord.Embed(
            title="💰 Balance",
            description=f"{target.display_name} has **{balance} coins**",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.command(name='pay', description="Transfer coins to another user.")
    @app_commands.describe(recipient="Member to transfer coins to", amount="How much would you like to transfer?")
    async def transfer(self, interaction: discord.Interaction,
                       recipient: discord.Member,
                       amount: app_commands.Range[int, 1]):
        """Command for transferring coins"""
        sender_id = str(interaction.user.id)
        recipient_id = str(recipient.id)

        if sender_id == recipient_id:
            return await interaction.response.send_message(
                "❌ You can't pay yourself!",
                ephemeral=True
            )

        sender_balance = self.economy.get_balance(sender_id)
        if sender_balance < amount:
            return await interaction.response.send_message(
                f"❌ Insufficient funds! You only have {sender_balance} coins.",
                ephemeral=True
            )

        self.economy.update_balance(sender_id, -amount)
        self.economy.update_balance(recipient_id, amount)

        embed = discord.Embed(
            title="✅ Transfer Complete",
            description=f"{interaction.user.mention} → {recipient.mention}",
            color=discord.Color.green()
        )
        embed.add_field(name="Amount", value=f"{amount} coins", inline=False)
        embed.add_field(name="New Balances",
                        value=f"{interaction.user.display_name}: {self.economy.get_balance(sender_id)}\n{recipient.display_name}: {self.economy.get_balance(recipient_id)}",
                        inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.checks.cooldown(1, 30.0)
    @app_commands.command(name="leaderboard", description="Shows server's richest members")
    async def leaderboard(self, interaction: discord.Interaction):
        """Displays top 10 users by wealth distribution"""

        member_files = list(self.economy.members_dir.glob("*.json"))
        if not member_files:
            return await interaction.response.send_message("❌ No economy data found!", ephemeral=True)

        balances = []
        for file in member_files:
            try:
                with open(file, 'r') as f:
                    data = json.load(f)
                    user_id = file.stem
                    balances.append((user_id, data.get("balance", 0)))
            except (json.JSONDecodeError, KeyError):
                continue

        balances.sort(key=lambda x: x[1], reverse=True)
        top_10 = balances[:10]
        total_wealth = sum(balance for _, balance in top_10) or 1

        embed = discord.Embed(
            title="💰 Server Wealth Leaderboard",
            color=0xf1c40f,
            timestamp=interaction.created_at
        )

        rank_icons = ["🥇", "🥈", "🥉"] + ["·"] * 7
        leaderboard_text = []

        for idx, ((user_id, balance), icon) in enumerate(zip(top_10, rank_icons), 1):
            member = interaction.guild.get_member(int(user_id)) or await self.bot.fetch_user(int(user_id))
            display_name = getattr(member, "display_name", f"User {user_id}")

            if idx <= 3:
                leaderboard_text.append(f"{icon} **{display_name}**: `{balance:,} coins` {'👑' if idx == 1 else ''}")
            else:
                leaderboard_text.append(f"{icon} {display_name}: `{balance:,} coins`")

        embed.description = "\n".join(leaderboard_text)

        if top_10:
            embed.add_field(
                name="📊 Wealth Distribution",
                value="*Percentage of top 10 total wealth*",
                inline=False
            )

            for user_id, balance in top_10[:5]:
                member = interaction.guild.get_member(int(user_id)) or await self.bot.fetch_user(int(user_id))
                percentage = (balance / total_wealth) * 100
                progress = int(percentage / 5)

                embed.add_field(
                    name=f"{getattr(member, 'display_name', f'User {user_id}')}",
                    value=f"`{'█' * progress}{'░' * (20 - progress)}` {percentage:.1f}%",
                    inline=False
                )

        embed.set_footer(
            text=f"Total tracked users: {len(balances)} | Combined top 10 wealth: {total_wealth:,} coins",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None
        )

        embed.set_thumbnail(url="https://i.postimg.cc/CKXkv5Jk/Video-Game-Gold-Coin-Transparent.png")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(
        Economy(bot),
        guilds=[
            discord.Object(id=771099589713199145),
            discord.Object(id=601677205445279744)
        ]
    )
