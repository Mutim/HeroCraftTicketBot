import asyncio
import random
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiofiles
import discord
from discord import app_commands, TextStyle
from discord.ext import commands, tasks
from discord.ui import Select, View, Button, Modal, TextInput

from lib.cogs.economy import EconomyUtils

# Configuration Constants
MAX_TICKETS_PER_USER = 5
TICKET_PRICE = 100
DRAWING_HOUR = 20  # 8 PM
DRAWING_MINUTE = 0
DAILY_INTERVAL = timedelta(days=1)
ANNOUNCEMENT_CHANNEL_ID = 602014224910385163


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
        cog = interaction.client.get_cog("MegaMillions")
        await cog.process_ticket_purchase(
            interaction,
            numbers=self.numbers.value,
            powerball=self.powerball.value
        )


class LotteryView(View):
    def __init__(self, cog):
        super().__init__(timeout=120)
        self.cog = cog
        self.message = None

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass

    @discord.ui.button(label="Purchase Ticket", style=discord.ButtonStyle.green, custom_id="purchase_ticket")
    async def purchase_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(PurchaseTicketModal())

    @discord.ui.button(label="Quick Pick", style=discord.ButtonStyle.blurple, custom_id="quick_pick")
    async def quick_pick(self, interaction: discord.Interaction, button: Button):
        """Automatically generate random numbers"""
        cog = self.cog
        user_id = interaction.user.id

        # Check ticket limit
        current_tickets = await cog.get_member_tickets(user_id)
        if len(current_tickets) >= MAX_TICKETS_PER_USER:
            return await interaction.response.send_message(
                f"You've reached the limit of {MAX_TICKETS_PER_USER} tickets!",
                ephemeral=True
            )

        # Process payment
        user_balance = cog.economy.get_balance(user_id)
        if user_balance < TICKET_PRICE:
            return await interaction.response.send_message(
                f"You need {TICKET_PRICE} coins to buy a ticket!",
                ephemeral=True
            )

        # Generate random ticket
        new_ticket = {
            "numbers": sorted(random.sample(range(1, 71), 5)),
            "powerball": random.randint(1, 25),
            "purchase_time": datetime.now(timezone.utc).isoformat()
        }

        # Save ticket
        current_tickets.append(new_ticket)
        await cog.save_member_tickets(user_id, current_tickets)

        # Update pot
        cog.current_pot += TICKET_PRICE * cog.pot_multiplier
        cog.save_lottery_data()

        # Send confirmation
        embed = discord.Embed(
            title="🎫 Quick Pick Ticket Purchased!",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Your Numbers",
            value=f"{', '.join(map(str, new_ticket['numbers']))} PB: {new_ticket['powerball']}"
        )
        embed.set_footer(text=f"Added {TICKET_PRICE * cog.pot_multiplier} coins to the pot")

        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self.update_main_embed(interaction)

    @discord.ui.button(label="My Tickets", style=discord.ButtonStyle.gray, custom_id="my_tickets")
    async def show_tickets(self, interaction: discord.Interaction, button: Button):
        """Show current tickets with management options"""
        cog = self.cog
        tickets = await cog.get_member_tickets(interaction.user.id)

        if not tickets:
            return await interaction.response.send_message(
                "You don't have any tickets yet!",
                ephemeral=True
            )

        # Create ticket management view
        view = TicketManagementView(cog, tickets)
        embed = await cog._format_tickets_embed(interaction.user.id)

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )
        view.message = await interaction.original_response()

    async def update_main_embed(self, interaction: discord.Interaction):
        """Refresh the main lottery embed"""
        cog = self.cog
        embed = await cog.format_main_embed(interaction.user.id)
        await interaction.edit_original_response(embed=embed, view=self)


class TicketManagementView(View):
    """Reusing your existing ticket management system"""

    def __init__(self, cog, tickets: list):
        super().__init__(timeout=120)
        self.cog = cog
        self.tickets = tickets
        self.add_item(TicketDropdown(cog, tickets))

    async def on_timeout(self):
        if hasattr(self, 'message'):
            try:
                await self.message.delete()
            except discord.NotFound:
                pass


class TicketDropdown(Select):
    """Your existing dropdown modified for reuse"""

    def __init__(self, cog, tickets: List[dict]):
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
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        current_tickets = await self.cog.get_member_tickets(user_id)

        selected_indexes = sorted((int(i) for i in self.values), reverse=True)
        torn_tickets = []

        for idx in selected_indexes:
            torn_tickets.append(current_tickets.pop(idx))

        await self.cog.save_member_tickets(user_id, current_tickets)

        # Send confirmation
        embed = discord.Embed(
            title="🗑️ Tickets Torn Up",
            color=discord.Color.red()
        )
        for ticket in torn_tickets:
            embed.add_field(
                name=f"Removed ticket",
                value=f"Numbers: {', '.join(map(str, ticket['numbers']))} PB: {ticket['powerball']}",
                inline=False
            )

        self.view.stop()
        await interaction.response.edit_message(
            embed=embed,
            view=None
        )

        # Refresh main lottery view
        main_view = LotteryView(self.cog)
        main_embed = await self.cog.format_main_embed(user_id)
        message = await interaction.original_response()
        await message.edit(embed=main_embed, view=main_view)


class TicketDropdownView(View):
    def __init__(self, cog, tickets: list):
        super().__init__(timeout=120)
        self.cog = cog
        self.add_item(TicketDropdown(cog, tickets))

    async def on_timeout(self):
        if hasattr(self, 'message'):
            try:
                await self.message.delete()
            except discord.NotFound:
                pass


class MegaMillions(commands.Cog):
    def __init__(self, bot: commands.Bot, economy_utils):
        self.bot = bot
        self.economy = economy_utils
        self.ticket_price = TICKET_PRICE
        self.pot_multiplier = 2
        self.members_dir = Path("lib/members")
        self.lottery_data_file = Path("data/lottery_data/lottery_data.json")
        self.file_lock = asyncio.Lock()

        # Initialize lottery data
        self.lottery_data = self._load_lottery_data()
        self.current_pot = self.lottery_data.get("current_pot", 0)
        drawing_time_str = self.lottery_data.get("drawing_time")
        if drawing_time_str:
            self.drawing_time = datetime.fromisoformat(drawing_time_str)
            if self.drawing_time.tzinfo is None:
                self.drawing_time = self.drawing_time.replace(tzinfo=timezone.utc)
        else:
            self._reset_drawing_time()
            self.drawing_time = datetime.fromisoformat(self.lottery_data["drawing_time"])

        self.winning_numbers: Optional[List[int]] = None
        self.winning_powerball: Optional[int] = None

        self.daily_drawing.start()

        self.members_dir.mkdir(parents=True, exist_ok=True)
        self.lottery_data_file.parent.mkdir(parents=True, exist_ok=True)

    async def cog_unload(self):
        """Clean up when the cog is unloaded"""
        self.daily_drawing.cancel()
        print("Lottery Cog Unloaded")

    async def cog_load(self):
        print("Lottery Cog Loaded")

    # File Operations
    def _load_lottery_data(self) -> dict:
        default_data = {
            "current_pot": 0,
            "active_participants": [],
            "drawing_time": ""
        }
        try:
            if self.lottery_data_file.exists():
                with open(self.lottery_data_file, 'r') as f:
                    loaded_data = json.load(f)
                    return {**default_data, **loaded_data}
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading lottery data: {e}")
        return default_data

    def save_lottery_data(self):
        self.lottery_data["current_pot"] = self.current_pot
        try:
            with open(self.lottery_data_file, 'w') as f:
                json.dump(self.lottery_data, f, indent=2)
            print(f"Saved lottery data. Current pot: {self.current_pot}")
        except IOError as e:
            print(f"Error saving lottery data: {e}")

    async def _save_member_data(self, user_id: int, data: dict):
        async with self.file_lock:
            try:
                file_path = self.members_dir / f"{user_id}.json"
                # Ensure directory exists
                file_path.parent.mkdir(exist_ok=True, parents=True)
                async with aiofiles.open(file_path, 'w') as f:
                    await f.write(json.dumps(data, indent=2))
                print(f"Successfully saved data for {user_id}")  # Debug
            except Exception as e:
                print(f"Error saving member data: {e}")
                raise  # Re-raise to see the error

    async def _load_member_data(self, user_id: int) -> dict:
        async with self.file_lock:
            try:
                file_path = self.members_dir / f"{user_id}.json"
                if file_path.exists():
                    async with aiofiles.open(file_path, 'r') as f:
                        return json.loads(await f.read())
            except (IOError, json.JSONDecodeError):
                return {}
        return {}

    # Drawing Management
    def _reset_drawing_time(self):
        now = datetime.now(timezone.utc)
        next_draw = now.replace(
            hour=DRAWING_HOUR,
            minute=DRAWING_MINUTE,
            second=0,
            microsecond=0
        )
        if next_draw <= now:
            next_draw += DAILY_INTERVAL
        self.lottery_data["drawing_time"] = next_draw.isoformat()
        self.save_lottery_data()

    @tasks.loop(minutes=1)
    async def daily_drawing(self):
        try:
            now = datetime.now(timezone.utc)
            if now >= self.drawing_time:
                await self.draw_winner()
                self._reset_drawing_time()
                # Reload the drawing time (already timezone-aware from _reset_drawing_time)
                self.drawing_time = datetime.fromisoformat(self.lottery_data["drawing_time"])
        except Exception as e:
            print(f"Error in daily drawing: {e}")
            # Consider proper error logging here

    # Ticket Operations
    async def get_member_tickets(self, user_id: int) -> List[dict]:
        data = await self._load_member_data(user_id)
        return data.get("lottery_tickets", [])

    async def save_member_tickets(self, user_id: int, tickets: List[dict]):
        data = await self._load_member_data(user_id)
        data["lottery_tickets"] = tickets
        await self._save_member_data(user_id, data)
        await self._add_participant(user_id)

    async def _clear_member_tickets(self, user_id: int):
        data = await self._load_member_data(user_id)
        if "lottery_tickets" in data:
            del data["lottery_tickets"]
            await self._save_member_data(user_id, data)

    async def _add_participant(self, user_id: int):
        if user_id not in self.lottery_data["active_participants"]:
            self.lottery_data["active_participants"].append(user_id)
            self.save_lottery_data()

    # Drawing Logic
    def generate_winning_numbers(self) -> Tuple[List[int], int]:
        white_balls = sorted(random.sample(range(1, 71), 5))
        powerball = random.randint(1, 25)
        return white_balls, powerball

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
        if channel := self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID):
            await channel.send(embed=embed)

    async def _format_tickets_embed(self, user_id: int) -> discord.Embed:
        """Helper to create an embed showing user's current tickets"""
        tickets = await self.get_member_tickets(user_id)
        embed = discord.Embed(
            title="Your Current Tickets",
            color=discord.Color.blue()
        )

        if not tickets:
            embed.description = "You have no tickets yet!"
            return embed

        for i, ticket in enumerate(tickets, 1):
            embed.add_field(
                name=f"Ticket #{i}",
                value=f"Numbers: {', '.join(map(str, ticket['numbers']))}\nPowerball: {ticket['powerball']}",
                inline=False
            )

        embed.set_footer(text=f"Total tickets: {len(tickets)}/{MAX_TICKETS_PER_USER}")
        return embed

    async def format_main_embed(self, user_id: int) -> discord.Embed:
        """Create the main lottery information embed"""
        tickets = await self.get_member_tickets(user_id)
        user = self.bot.get_user(user_id)

        embed = discord.Embed(
            title="🎰 Mega Millions Lottery",
            color=discord.Color.gold()
        )

        # Current jackpot and prizes
        embed.add_field(
            name="💰 Current Jackpot",
            value=f"{self.current_pot:,} coins",
            inline=False
        )

        # Prize breakdown
        prize_info = (
            "5+PB: JACKPOT (100%)\n"
            "5: 50% of pot\n"
            "4+PB: 40%\n"
            "4: 30%\n"
            "3+PB: 25%\n"
            "3: 20%\n"
            "2+PB: 15%\n"
            "1+PB: 10%"
        )
        embed.add_field(name="🏆 Prize Breakdown", value=prize_info, inline=True)

        # User's tickets and next draw
        embed.add_field(
            name="🎫 Your Tickets",
            value=f"You have {len(tickets)}/{MAX_TICKETS_PER_USER} tickets",
            inline=True
        )

        embed.add_field(
            name="⏰ Next Drawing",
            value=f"<t:{int(self.drawing_time.timestamp())}:R>",
            inline=False
        )

        # Current winning numbers (if available)
        if self.winning_numbers:
            embed.add_field(
                name="🏅 Previous Winning Numbers",
                value=f"**{', '.join(map(str, self.winning_numbers))}** PB: __{self.winning_powerball}__",
                inline=False
            )

        embed.set_footer(text=f"Ticket price: {TICKET_PRICE} coins each")
        return embed

    @app_commands.command(name="lottery", description="View and participate in the Mega Millions lottery")
    async def lottery(self, interaction: discord.Interaction):
        """Main lottery command"""
        embed = await self.format_main_embed(interaction.user.id)
        view = LotteryView(self)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    async def process_ticket_purchase(self, interaction: discord.Interaction, numbers: str, powerball: str):
        """Handle ticket purchase from modal"""
        try:
            # Validate powerball
            pb = int(powerball)
            if not 1 <= pb <= 25:
                raise ValueError

            # Validate main numbers
            nums = [int(n.strip()) for n in numbers.split(",")]
            if len(nums) != 5 or any(n < 1 or n > 70 for n in nums):
                raise ValueError

            # Check ticket limit
            current_tickets = await self.get_member_tickets(interaction.user.id)
            if len(current_tickets) >= MAX_TICKETS_PER_USER:
                return await interaction.response.send_message(
                    f"You've reached the limit of {MAX_TICKETS_PER_USER} tickets!",
                    ephemeral=True
                )

            # Process payment
            user_balance = self.economy.get_balance(interaction.user.id)
            if user_balance < TICKET_PRICE:
                return await interaction.response.send_message(
                    f"You need {TICKET_PRICE} coins to buy a ticket!",
                    ephemeral=True
                )

            self.economy.update_balance(interaction.user.id, -TICKET_PRICE)

            # Generate and add ticket
            new_ticket = {
                "numbers": sorted(nums),
                "powerball": pb,
                "purchase_time": datetime.now(timezone.utc).isoformat()
            }
            current_tickets.append(new_ticket)
            await self.save_member_tickets(interaction.user.id, current_tickets)

            # Update pot
            self.current_pot += TICKET_PRICE * self.pot_multiplier
            self.save_lottery_data()

            # Send confirmation
            embed = discord.Embed(
                title="🎫 Ticket Purchased!",
                description=f"Added {TICKET_PRICE * self.pot_multiplier} coins to the pot",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Your Numbers",
                value=f"{', '.join(map(str, new_ticket['numbers']))} PB: {new_ticket['powerball']}"
            )
            embed.set_footer(text=f"New pot total: {self.current_pot:,} coins")

            # Update original message
            original_view = LotteryView(self)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            main_embed = await self.format_main_embed(interaction.user.id)
            await interaction.edit_original_response(embed=main_embed, view=original_view)

        except ValueError:
            await interaction.response.send_message(
                "Invalid numbers! Please provide:\n"
                "- 5 numbers between 1-70 (comma separated)\n"
                "- 1 powerball between 1-25",
                ephemeral=True
            )

    async def draw_winner(self):
        self.winning_numbers, self.winning_powerball = self.generate_winning_numbers()

        if not self.lottery_data["active_participants"]:
            await self._announce_no_winners()
            return

        winners = []
        for user_id in self.lottery_data["active_participants"]:
            tickets = await self.get_member_tickets(user_id)
            for ticket in tickets:
                matched = len(set(ticket['numbers']) & set(self.winning_numbers))
                has_pb = (ticket['powerball'] == self.winning_powerball)
                if prize_tier := self.determine_prize_tier(matched, has_pb):
                    winners.append((user_id, matched, has_pb, prize_tier))
            await self._clear_member_tickets(user_id)

        # Process payouts
        total_payout = 0
        payouts = []
        prize_distribution = {
            "1_PB": 0.10, "2_PB": 0.15, "3": 0.20,
            "3_PB": 0.25, "4": 0.30, "4_PB": 0.40,
            "5": 0.50, "JACKPOT": 1.0
        }

        for tier, winners_in_tier in self.group_winners_by_tier(winners).items():
            if not winners_in_tier:
                continue

            prize_per_winner = (self.current_pot * prize_distribution[tier]) / len(winners_in_tier)
            for user_id, _, _, _ in winners_in_tier:
                self.economy.update_balance(user_id, prize_per_winner)
                payouts.append((user_id, prize_per_winner, tier))
                total_payout += prize_per_winner

        # Update state
        self.current_pot -= total_payout
        self.drawing_time = datetime.now(timezone.utc) + timedelta(days=1)

        self.lottery_data["active_participants"] = []
        self.lottery_data["drawing_time"] = self.drawing_time.isoformat()
        self.save_lottery_data()
        await self.announce_winners(payouts)

    def determine_prize_tier(self, matched: int, has_powerball: bool) -> Optional[str]:
        prize_map = {
            (5, True): "JACKPOT",
            (5, False): "5",
            (4, True): "4_PB",
            (4, False): "4",
            (3, True): "3_PB",
            (3, False): "3",
            (2, True): "2_PB",
            (1, True): "1_PB"
        }
        return prize_map.get((matched, has_powerball), None)

    def group_winners_by_tier(self, winners: List[Tuple]) -> Dict[str, List]:
        tiers = {
            "1_PB": [],
            "2_PB": [],
            "3": [],
            "3_PB": [],
            "4": [],
            "4_PB": [],
            "5": [],
            "JACKPOT": []
        }

        for winner in winners:
            tiers[winner[3]].append(winner)

        return tiers

    async def announce_winners(self, payouts: List[Tuple]):
        embed = discord.Embed(
            title="🎉 Mega Millions Drawing Results!",
            description=f"Winning Numbers: **{', '.join(map(str, self.winning_numbers))}** Powerball: **{self.winning_powerball}**\n"
                        f"Total pot: {self.current_pot + sum(p[1] for p in payouts)} coins\n"
                        f"Total paid out: {sum(p[1] for p in payouts)} coins\n"
                        f"New pot: {self.current_pot} coins",
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
                    value=f"{user} won {amount:.2f} coins!",
                    inline=False
                )

            if len(payouts) > 10:
                embed.set_footer(text=f"Plus {len(payouts) - 10} more winners...")

        channel = self.bot.get_channel(602014224910385163)
        if channel:
            await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    economy_utils = EconomyUtils()
    await bot.add_cog(
        MegaMillions(bot, economy_utils),
        guilds=[
            discord.Object(id=771099589713199145),
            discord.Object(id=601677205445279744)
        ]
    )