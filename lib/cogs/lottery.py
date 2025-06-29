import asyncio
import random
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

import aiofiles
import discord
from discord import app_commands, TextStyle
from discord.ext import commands, tasks
from discord.ui import Select, View, Button, Modal, TextInput

from lib.cogs.economy import EconomyUtils

# Configuration Constants
MAX_TICKETS_PER_USER = 5
TICKET_PRICE = 100
POT_MULTIPLIER = 2
DRAWING_HOUR = 20  # 8 PM
DRAWING_MINUTE = 0
DAILY_INTERVAL = timedelta(days=1)
ANNOUNCEMENT_CHANNEL_ID = 602014224910385163
LOGS_DIR = Path("data/casino_logs")
LOG_FILE_FORMAT = "lottery_{date}.json"

PRIZE_DISTRIBUTION = {
    "1_PB": 0.10, "2_PB": 0.15, "3": 0.20,
    "3_PB": 0.25, "4": 0.30, "4_PB": 0.40,
    "5": 0.50, "JACKPOT": 1.0
}


class PurchaseTicketModal(Modal, title="Purchase Lottery Ticket"):
    numbers = TextInput(
        label="Your 5 numbers (1-70, comma separated)",
        placeholder="Example: 1,2,3,4,5",
        style=TextStyle.short,
        required=True
    )

    powerball = TextInput(
        label="Powerball number (1-25)",
        placeholder="Enter a number between 1-25",
        style=TextStyle.short,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.client.get_cog("MegaMillions").process_ticket_purchase(
            interaction,
            numbers=self.numbers.value,
            powerball=self.powerball.value
        )


class LotteryView(View):
    def __init__(self, cog):
        super().__init__(timeout=120)
        self.cog = cog

    async def on_timeout(self):
        if hasattr(self, 'message'):
            for item in self.children:
                item.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass

    @discord.ui.button(label="Quick Pick", style=discord.ButtonStyle.green)
    async def quick_pick(self, interaction: discord.Interaction, button: Button):
        cog = self.cog
        user_id = interaction.user.id
        user_balance = cog.economy.get_balance(user_id)

        if len(await cog.get_member_tickets(user_id)) >= MAX_TICKETS_PER_USER:
            return await interaction.response.send_message(
                f"You've reached the limit of {MAX_TICKETS_PER_USER} tickets!",
                ephemeral=True
            )

        if user_balance < TICKET_PRICE:
            return await interaction.response.send_message(
                f"You need {TICKET_PRICE} coins to buy a ticket!",
                ephemeral=True
            )

        # Process payment first
        cog.economy.update_balance(user_id, -TICKET_PRICE)

        new_ticket = {
            "numbers": sorted(random.sample(range(1, 71), 5)),
            "powerball": random.randint(1, 25),
            "purchase_time": datetime.now(timezone.utc).isoformat()
        }

        current_tickets = await cog.get_member_tickets(user_id)
        current_tickets.append(new_ticket)
        await cog.save_member_tickets(user_id, current_tickets)
        cog.current_pot += TICKET_PRICE * POT_MULTIPLIER
        cog.save_lottery_data()

        await interaction.response.defer()

        confirm_embed = discord.Embed(
            title="🎫 Quick Pick Purchased!",
            description=f"Added {TICKET_PRICE * POT_MULTIPLIER} coins to the pot",
            color=discord.Color.green()
        )
        confirm_embed.add_field(
            name="Your Numbers",
            value=f"{', '.join(map(str, new_ticket['numbers']))} PB: {new_ticket['powerball']}\n\nCurrent Balance: {user_balance}"
        )

        main_embed = await cog.format_main_embed(user_id)
        await interaction.edit_original_response(
            embed=main_embed,
            view=self
        )

        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

    @discord.ui.button(label="Manual Pick", style=discord.ButtonStyle.blurple)
    async def purchase_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PurchaseTicketModal())

    @discord.ui.button(label="My Tickets", style=discord.ButtonStyle.gray)
    async def show_tickets(self, interaction: discord.Interaction, button: Button):
        tickets = await self.cog.get_member_tickets(interaction.user.id)
        if not tickets:
            return await interaction.response.send_message(
                "You don't have any tickets yet!",
                ephemeral=True
            )

        view = TicketManagementView(self.cog, tickets)
        await interaction.response.send_message(
            embed=await self.cog._format_tickets_embed(interaction.user.id),
            view=view,
            ephemeral=True
        )
        view.message = await interaction.original_response()

    @discord.ui.button(label="Show Odds", style=discord.ButtonStyle.red)
    async def show_odds(self, interaction: discord.Interaction, button: Button):
        """Show the odds and prize structure in a new embed"""
        embed = discord.Embed(
            title="📊 Mega Millions Odds & Prizes",
            color=discord.Color.gold()
        )

        # Odds section
        embed.add_field(
            name="ODDS",
            value=(
                "Jackpot (5+PB): 1 in 302,575,350\n"
                "Any Prize: 1 in 24.9\n"
                "\n"
                "*May the odds be ever in your favor*"
            ),
            inline=False
        )

        # Prize structure section
        current_pot = self.cog.current_pot
        prize_table = (
            "```\n"
            "┌───────────────────┬──────────────────┐\n"
            "│      Matches      │      Payout      │\n"
            "├───────────────────┼──────────────────┤\n"
            f"│  5 + Powerball    │ {str(current_pot * 1.0) + ' coins':<16} │\n"
            f"│  5 numbers        │ {str(round(current_pot * 0.5)) + ' coins':<16} │\n"
            f"│  4 + Powerball    │ {str(round(current_pot * 0.4)) + ' coins':<16} │\n"
            f"│  4 numbers        │ {str(round(current_pot * 0.3)) + ' coins':<16} │\n"
            f"│  3 + Powerball    │ {str(round(current_pot * 0.25)) + ' coins':<16} │\n"
            f"│  3 numbers        │ {str(round(current_pot * 0.2)) + ' coins':<16} │\n"
            f"│  2 + Powerball    │ {str(round(current_pot * 0.15)) + ' coins':<16} │\n"
            f"│  1 + Powerball    │ {str(round(current_pot * 0.1)) + ' coins':<16} │\n"
            "└───────────────────┴──────────────────┘\n"
            "```"
        )

        embed.add_field(
            name="PRIZE STRUCTURE",
            value=prize_table,
            inline=False
        )

        embed.set_footer(text=f"Current pot: {current_pot:,} coins")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _update_ui(self, interaction: discord.Interaction, new_ticket: dict):
        user_id = interaction.user.id
        user_balance = self.economy.get_balance(user_id)
        embed = discord.Embed(
            title="🎫 Quick Pick Ticket Purchased!",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Your Numbers",
            value=f"{', '.join(map(str, new_ticket['numbers']))} PB: {new_ticket['powerball']}"
        )
        embed.set_footer(text=f"Added {TICKET_PRICE * POT_MULTIPLIER} coins to the pot\n\nCurrent Balance: {user_balance}")

        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self._refresh_main_embed(interaction)

    async def _refresh_main_embed(self, interaction: discord.Interaction):
        embed = await self.cog.format_main_embed(interaction.user.id)
        await interaction.edit_original_response(embed=embed, view=self)


class TicketManagementView(View):
    def __init__(self, cog, tickets: list):
        super().__init__(timeout=120)
        self.cog = cog
        self.add_item(TicketDropdown(tickets))

    async def on_timeout(self):
        if hasattr(self, 'message'):
            try:
                await self.message.delete()
            except discord.NotFound:
                pass


class TicketDropdown(Select):
    def __init__(self, tickets: List[dict]):
        options = [
            discord.SelectOption(
                label=f"Ticket #{i + 1}",
                description=f"Numbers: {', '.join(map(str, t['numbers']))} PB: {t['powerball']}",
                value=str(i)
            ) for i, t in enumerate(tickets)
        ]
        super().__init__(
            placeholder="Select tickets to tear up...",
            min_values=1,
            max_values=len(tickets),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("MegaMillions")
        user_id = interaction.user.id
        current_tickets = await cog.get_member_tickets(user_id)

        selected_indexes = sorted((int(i) for i in self.values), reverse=True)
        torn_tickets = [current_tickets.pop(idx) for idx in selected_indexes]

        await cog.save_member_tickets(user_id, current_tickets)

        embed = discord.Embed(title="🗑️ Tickets Torn Up", color=discord.Color.red())
        for ticket in torn_tickets:
            embed.add_field(
                name="Removed ticket",
                value=f"Numbers: {', '.join(map(str, ticket['numbers']))} PB: {ticket['powerball']}",
                inline=False
            )

        self.view.stop()
        await interaction.response.edit_message(embed=embed, view=None)

        main_view = LotteryView(cog)
        main_embed = await cog.format_main_embed(user_id)
        await interaction.edit_original_response(embed=main_embed, view=main_view)


class MegaMillions(commands.Cog):
    def __init__(self, bot: commands.Bot, economy_utils):
        self.bot = bot
        self.economy = economy_utils
        self.ticket_price = TICKET_PRICE
        self.members_dir = Path("lib/members")
        self.lottery_data_file = Path("data/lottery_data/lottery_data.json")
        self.file_lock = asyncio.Lock()

        self._initialize_data()
        self._ensure_directories_exist()
        self.daily_drawing.start()

    def _initialize_data(self):
        self.lottery_data = self._load_lottery_data()
        self.current_pot = self.lottery_data.get("current_pot", 0)
        self._set_drawing_time()

    def _ensure_directories_exist(self):
        self.members_dir.mkdir(parents=True, exist_ok=True)
        self.lottery_data_file.parent.mkdir(parents=True, exist_ok=True)

    async def _log_drawing_results(self, winners: List[Tuple], participants_with_tickets: Dict[int, List[dict]]):
        """Save drawing results to daily JSON log file"""
        try:
            now = datetime.now(timezone.utc)
            log_file = LOGS_DIR / LOG_FILE_FORMAT.format(date=now.date().isoformat())
            LOGS_DIR.mkdir(parents=True, exist_ok=True)

            entry = {
                "timestamp": now.isoformat(),
                "winning_numbers": self.winning_numbers,
                "powerball": self.winning_powerball,
                "pot_amount": self.current_pot,
                "winners": [],
                "non_winners": []
            }

            winning_user_ids = {user_id for user_id, *_ in winners}
            for user_id, matched, has_pb, tier in winners:
                user = self.bot.get_user(user_id)
                tickets = participants_with_tickets[user_id]

                entry["winners"].append({
                    "user_id": user_id,
                    "username": user.name if user else str(user_id),
                    "matched_numbers": matched,
                    "had_powerball": has_pb,
                    "prize_tier": tier,
                    "prize_amount": self.current_pot * PRIZE_DISTRIBUTION[tier],
                    "tickets": tickets
                })

            for user_id, tickets in participants_with_tickets.items():
                if user_id not in winning_user_ids:
                    user = self.bot.get_user(user_id)
                    entry["non_winners"].append({
                        "user_id": user_id,
                        "username": user.name if user else str(user_id),
                        "tickets_purchased": len(tickets),
                        "tickets": tickets,
                        "total_spent": len(tickets) * TICKET_PRICE
                    })

            existing_logs = []
            if log_file.exists():
                async with aiofiles.open(log_file, 'r') as f:
                    existing_logs = json.loads(await f.read())

            existing_logs.append(entry)

            async with aiofiles.open(log_file, 'w') as f:
                await f.write(json.dumps(existing_logs, indent=2))

        except Exception as e:
            print(f"Error saving lottery log: {e}")

    def _load_lottery_data(self) -> dict:
        default_data = {
            "current_pot": 0,
            "active_participants": [],
            "drawing_time": ""
        }
        try:
            if self.lottery_data_file.exists():
                with open(self.lottery_data_file) as f:
                    return {**default_data, **json.load(f)}
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading lottery data: {e}")
        return default_data

    def _set_drawing_time(self):
        if drawing_time_str := self.lottery_data.get("drawing_time"):
            self.drawing_time = datetime.fromisoformat(drawing_time_str)
            if self.drawing_time.tzinfo is None:
                self.drawing_time = self.drawing_time.replace(tzinfo=timezone.utc)
        else:
            self._reset_drawing_time()

    def _reset_drawing_time(self):
        now = datetime.now(timezone.utc)
        next_draw = now.replace(
            hour=DRAWING_HOUR,
            minute=DRAWING_MINUTE,
            second=0,
            microsecond=0
        )

        if now >= next_draw:
            next_draw += DAILY_INTERVAL

        self.lottery_data["drawing_time"] = next_draw.isoformat()
        self.drawing_time = next_draw
        self.save_lottery_data()

    async def cog_load(self):
        self._reset_drawing_time()
        # self.daily_drawing.start()
        print("Lottery Cog Loaded")

    async def cog_unload(self):
        print("Lottery Cog Unloaded")

    @tasks.loop(minutes=1)
    async def daily_drawing(self):
        if datetime.now(timezone.utc) >= self.drawing_time:
            await self._process_drawing()

    async def _process_drawing(self):
        self.winning_numbers, self.winning_powerball = self._generate_winning_numbers()
        all_participants = set(self.lottery_data["active_participants"])

        if not all_participants:
            await self._announce_no_winners()
            return

        participants_with_tickets = {
            user_id: await self.get_member_tickets(user_id)
            for user_id in all_participants
        }

        winners = await self._evaluate_tickets()
        payouts = await self._distribute_prizes(winners)

        await self._log_drawing_results(winners, participants_with_tickets)

        for user_id in all_participants:
            await self._clear_member_tickets(user_id)

        await self._reset_after_drawing(payouts)

    def _generate_winning_numbers(self) -> Tuple[List[int], int]:
        return sorted(random.sample(range(1, 71), 5)), random.randint(1, 25)

    async def _announce_no_winners(self):
        embed = discord.Embed(
            title="🎟️ Mega Millions Drawing",
            description=f"No tickets were sold! Pot rolls over: {self.current_pot} coins",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Winning Numbers",
            value=f"**{', '.join(map(str, self.winning_numbers))}** PB: {self.winning_powerball}",
            inline=False
        )
        await self._send_announcement(embed)

    async def _evaluate_tickets(self) -> List[Tuple]:
        winners = []
        for user_id in self.lottery_data["active_participants"]:
            for ticket in await self.get_member_tickets(user_id):
                matched = len(set(ticket['numbers']) & set(self.winning_numbers))
                has_pb = (ticket['powerball'] == self.winning_powerball)
                if prize_tier := self._determine_prize_tier(matched, has_pb):
                    winners.append((user_id, matched, has_pb, prize_tier))
            await self._clear_member_tickets(user_id)
        return winners

    def _determine_prize_tier(self, matched: int, has_powerball: bool) -> Optional[str]:
        return {
            (5, True): "JACKPOT",
            (5, False): "5",
            (4, True): "4_PB",
            (4, False): "4",
            (3, True): "3_PB",
            (3, False): "3",
            (2, True): "2_PB",
            (1, True): "1_PB"
        }.get((matched, has_powerball))

    async def _distribute_prizes(self, winners: List[Tuple]) -> List[Tuple]:
        payouts = []
        tier_groups = self._group_winners_by_tier(winners)

        for tier, winners_in_tier in tier_groups.items():
            if not winners_in_tier:
                continue

            prize_per_winner = (self.current_pot * PRIZE_DISTRIBUTION[tier]) / len(winners_in_tier)
            for user_id, *_ in winners_in_tier:
                self.economy.update_balance(user_id, prize_per_winner)
                payouts.append((user_id, prize_per_winner, tier))

        return payouts

    def _group_winners_by_tier(self, winners: List[Tuple]) -> Dict[str, List]:
        return {tier: [w for w in winners if w[3] == tier] for tier in PRIZE_DISTRIBUTION}

    async def _reset_after_drawing(self, payouts: List[Tuple]):
        total_payout = sum(p[1] for p in payouts)
        self.current_pot -= total_payout
        self.lottery_data["active_participants"] = []
        self._reset_drawing_time()
        await self.announce_winners(payouts)

    async def announce_winners(self, payouts: List[Tuple]):
        embed = discord.Embed(
            title="🎉 Mega Millions Drawing Results!",
            description=(
                f"Winning Numbers: **{', '.join(map(str, self.winning_numbers))}** "
                f"Powerball: **{self.winning_powerball}**\n"
                f"Total paid out: {sum(p[1] for p in payouts):,} coins\n"
                f"New pot: {self.current_pot:,} coins"
            ),
            color=discord.Color.gold()
        )

        if not payouts:
            embed.add_field(
                name="No Winners",
                value="No one matched enough numbers to win this drawing!",
                inline=False
            )
        else:
            for i, (user_id, amount, tier) in enumerate(payouts[:10], 1):
                user = self.bot.get_user(user_id) or f"User {user_id}"
                embed.add_field(
                    name=f"Winner #{i} - {tier.replace('_', ' ').title()}",
                    value=f"{user} won {amount:,.2f} coins!",
                    inline=False
                )

            if len(payouts) > 10:
                embed.set_footer(text=f"Plus {len(payouts) - 10} more winners...")

        await self._send_announcement(embed)

    async def _send_announcement(self, embed: discord.Embed):
        if channel := self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID):
            await channel.send(embed=embed)

    async def get_member_tickets(self, user_id: int) -> List[dict]:
        data = await self._load_member_data(user_id)
        return data.get("lottery_tickets", [])

    async def _add_ticket(self, user_id: int, ticket: dict):
        tickets = await self.get_member_tickets(user_id)
        tickets.append(ticket)
        await self.save_member_tickets(user_id, tickets)
        self._update_pot()

    def _update_pot(self):
        self.current_pot += TICKET_PRICE * POT_MULTIPLIER
        self.save_lottery_data()

    async def save_member_tickets(self, user_id: int, tickets: List[dict]):
        data = await self._load_member_data(user_id)
        data["lottery_tickets"] = tickets
        await self._save_member_data(user_id, data)
        await self._add_participant(user_id)

    async def _load_member_data(self, user_id: int) -> dict:
        async with self.file_lock:
            file_path = self.members_dir / f"{user_id}.json"
            if not file_path.exists():
                return {}
            try:
                async with aiofiles.open(file_path) as f:
                    return json.loads(await f.read())
            except (IOError, json.JSONDecodeError):
                return {}

    async def _save_member_data(self, user_id: int, data: dict):
        async with self.file_lock:
            file_path = self.members_dir / f"{user_id}.json"
            async with aiofiles.open(file_path, 'w') as f:
                await f.write(json.dumps(data, indent=2))

    async def _add_participant(self, user_id: int):
        if user_id not in self.lottery_data["active_participants"]:
            self.lottery_data["active_participants"].append(user_id)
            self.save_lottery_data()

    async def _clear_member_tickets(self, user_id: int):
        data = await self._load_member_data(user_id)
        if "lottery_tickets" in data:
            data.pop("lottery_tickets")
            await self._save_member_data(user_id, data)

    def save_lottery_data(self):
        self.lottery_data["current_pot"] = self.current_pot
        try:
            with open(self.lottery_data_file, 'w') as f:
                json.dump(self.lottery_data, f, indent=2)
        except IOError as e:
            print(f"Error saving lottery data: {e}")

    async def _format_tickets_embed(self, user_id: int) -> discord.Embed:
        tickets = await self.get_member_tickets(user_id)
        embed = discord.Embed(
            title="Your Current Tickets",
            color=discord.Color.blue()
        )

        for i, ticket in enumerate(tickets, 1):
            embed.add_field(
                name=f"Ticket #{i}",
                value=f"Numbers: {', '.join(map(str, ticket['numbers']))}\nPowerball: {ticket['powerball']}",
                inline=False
            )

        embed.set_footer(text=f"Total tickets: {len(tickets)}/{MAX_TICKETS_PER_USER}")
        return embed

    async def format_main_embed(self, user_id: int) -> discord.Embed:
        embed = discord.Embed(
            title="🎰 Mega Millions Lottery",
            color=discord.Color.gold()
        )

        embed.add_field(
            name="💰 Current Jackpot",
            value=f"{self.current_pot:,} coins\nCurrent Multiplier: {POT_MULTIPLIER}x Ticket Value",
            inline=False
        )

        # Button explanations
        embed.add_field(
            name="🎫 Ticket Options",
            value=(
                "• **Quick Pick**: Randomly generated numbers\n"
                "• **Purchase Ticket**: Choose your own numbers\n"
                "• **My Tickets**: View/delete your tickets\n"
                "• **Show Odds**: See winning probabilities\n\n"
                "  *The house will match you Ticket Price x Multiplier*"
            ),
            inline=False
        )

        ticket_count = len(await self.get_member_tickets(user_id))
        embed.add_field(
            name="🎫 Your Tickets",
            value=f"You have {ticket_count}/{MAX_TICKETS_PER_USER} tickets",
            inline=True
        )

        embed.add_field(
            name="⏰ Next Drawing",
            value=f"<t:{int(self.drawing_time.timestamp())}:R>",
            inline=True
        )

        embed.set_footer(text=f"Ticket price: {TICKET_PRICE} coins each")

        if hasattr(self, 'winning_numbers'):
            embed.add_field(
                name="🏅 Previous Winning Numbers",
                value=f"**{', '.join(map(str, self.winning_numbers))}** PB: __{self.winning_powerball}__",
                inline=False
            )

        return embed

    @app_commands.command(name="lottery", description="View and participate in the Mega Millions lottery")
    async def lottery(self, interaction: discord.Interaction):
        embed = await self.format_main_embed(interaction.user.id)
        view = LotteryView(self)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    async def process_ticket_purchase(self, interaction: discord.Interaction, numbers: str, powerball: str):
        try:
            nums = [int(n.strip()) for n in numbers.split(",")]
            pb = int(powerball)
            user_id = interaction.user.id
            user_balance = self.economy.get_balance(user_id)

            if (len(nums) != 5 or any(n < 1 or n > 70 for n in nums) or
                    not 1 <= pb <= 25):
                raise ValueError

            if len(await self.get_member_tickets(user_id)) >= MAX_TICKETS_PER_USER:
                return await interaction.response.send_message(
                    f"You've reached the limit of {MAX_TICKETS_PER_USER} tickets!",
                    ephemeral=True
                )

            if user_balance < TICKET_PRICE:
                return await interaction.response.send_message(
                    f"You need {TICKET_PRICE} coins to buy a ticket!",
                    ephemeral=True
                )

            self.economy.update_balance(user_id, -TICKET_PRICE)
            new_ticket = {
                "numbers": sorted(nums),
                "powerball": pb,
                "purchase_time": datetime.now(timezone.utc).isoformat()
            }

            await self._add_ticket(user_id, new_ticket)

            embed = discord.Embed(
                title="🎫 Ticket Purchased!",
                description=f"Added {TICKET_PRICE * POT_MULTIPLIER} coins to the pot",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Your Numbers",
                value=f"{', '.join(map(str, new_ticket['numbers']))} PB: {new_ticket['powerball']}\n\nYour Balance: {user_balance}"
            )
            embed.set_footer(text=f"New pot total: {self.current_pot:,} coins")

            await interaction.response.send_message(embed=embed, ephemeral=True)
            await interaction.edit_original_response(
                embed=await self.format_main_embed(user_id),
                view=LotteryView(self)
            )

        except ValueError:
            await interaction.response.send_message(
                "Invalid numbers! Please provide:\n"
                "- 5 numbers between 1-70 (comma separated)\n"
                "- 1 powerball between 1-25",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(
        MegaMillions(bot, EconomyUtils()),
        guilds=[
            discord.Object(id=771099589713199145),
            discord.Object(id=601677205445279744)
        ]
    )