import random
from pathlib import Path
import os
import discord
from discord import app_commands, ui
from discord.ext import commands
from typing import Dict, Tuple, List, Optional

from lib.cogs.economy import EconomyUtils


class RideTheBus(commands.Cog):
    def __init__(self, bot: commands.Bot, economy_utils: EconomyUtils):
        self.bot = bot
        self.economy = economy_utils
        self.games: Dict[int, 'RideTheBus.GameState'] = {}

    # Helper function
    def _add_common_embed_fields(self, embed: discord.Embed, interaction: discord.Interaction, game_state) -> discord.Embed:
        """Add common embed fields. (Footer, time stamp, etc to all embeds"""
        footer_text = f"Player: {interaction.user.display_name}"
        if game_state:
            footer_text += f" • Bet: {game_state.bet} coins"
        embed.set_footer(text=footer_text, icon_url=interaction.user.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()

        if game_state.cards:
            card_value = game_state.cards[-1][0]
            formatted_card = self.CARD_VALUE_DIGIT.get(card_value.lower(), card_value)
            formatted_suit = self.SUIT_ICONS[game_state.cards[-1][1]]
            card_key = f"{formatted_card}{formatted_suit}"

            try:
                embed.set_thumbnail(url=self.CARD_IMAGES[card_key])
                print(f'Displaying card: {card_key}')
            except KeyError:
                print(f"Missing card image for: {card_key}")
                embed.set_thumbnail(url='https://i.postimg.cc/HcbB3tr0/red-joker.png')

        return embed

    def format_card(self, card: Tuple[str, str]) -> str:
        """Formats card with color indicator and underline"""
        value, suit = card
        suit_icon = self.SUIT_ICONS.get(suit, '?')
        color = "R" if suit in ["hearts", "diamonds"] else "B"
        return f"**__{value.capitalize()} {suit_icon}__** ({color})"

    def format_choice(self, choice: str, round_num: int) -> str:
        """Formats the player's choice for display"""
        if round_num == 1:
            return "Red" if choice == "red" else "Black"
        elif round_num == 2:
            return "Higher" if choice == "higher" else "Lower"
        elif round_num == 3:
            return "Inside" if choice == "inside" else "Outside"
        elif round_num == 4:
            return {
                '♥': 'Hearts',
                '♦': 'Diamonds',
                '♣': 'Clubs',
                '♠': 'Spades'
            }.get(choice, choice)
        return choice

    def create_button_callback(self, choice: str):
        async def callback(interaction: discord.Interaction):
            await self.handle_round(interaction, choice)
        return callback

    class GameState:
        def __init__(self, bet: int):
            self.bet = bet
            self.current_round = 1
            self.cards: List[Tuple[str, str]] = []
            self.pot = bet
            self.cashed_out = False
            self.round_multipliers = {1: 2, 2: 3, 3: 5, 4: 10}
            self.last_choice: Optional[str] = None
            self.message: discord.Message | None = None

        def update_pot(self):
            self.pot = self.bet * self.round_multipliers[self.current_round]

    class GameView(ui.View):
        def __init__(self, game_cog: 'RideTheBus', user_id: int):
            super().__init__(timeout=120)
            self.game_cog = game_cog
            self.user_id = user_id
            self.cash_out_clicked = False
            self.active = True

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't your game!", ephemeral=True)
                return False
            return True

        async def on_timeout(self):
            """Called when the view times out"""
            if self.user_id in self.game_cog.games:
                del self.game_cog.games[self.user_id]

            try:
                if hasattr(self, 'message') and self.message:
                    for item in self.children:
                        item.disabled = True
                    await self.message.edit(view=self)
            except discord.NotFound:
                print("Message was not found")
            except Exception as e:
                print(f"Error in on_timeout: {e}")

        @ui.button(label="Cash Out", style=discord.ButtonStyle.green, emoji="💰")
        async def cash_out(self, interaction: discord.Interaction, button: ui.Button):
            self.cash_out_clicked = True
            game_state = self.game_cog.games[self.user_id]
            game_state.cashed_out = True

            for item in self.children:
                if isinstance(item, ui.Button):
                    item.disabled = True

            if not self.active:
                await interaction.response.send_message("Game expired", ephemeral=True)
                return

            await interaction.response.defer()
            self.stop()
            await self.game_cog.end_game(interaction, game_state)

    class PlayAgainView(ui.View):
        def __init__(self, game_cog: 'RideTheBus', user_id: int, last_bet: int):
            super().__init__(timeout=60)
            self.game_cog = game_cog
            self.user_id = user_id
            self.last_bet = last_bet

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't your game!", ephemeral=True)
                return False
            return True

        @ui.button(label="Play Again", style=discord.ButtonStyle.green, emoji="🎲")
        async def play_again(self, interaction: discord.Interaction, button: ui.Button):
            await interaction.response.defer()

            for item in self.children:
                item.disabled = True
            await interaction.edit_original_response(view=self)

            await self.game_cog.start_game(interaction, self.last_bet)

        async def on_timeout(self):
            if hasattr(self, 'message'):
                try:
                    for item in self.children:
                        item.disabled = True
                    await self.message.edit(view=self)
                except:
                    await self.message.edit(view=None)

    # Card constants
    CARD_VALUES = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "jack", "queen", "king", "ace"]
    CARD_SUITS = ["hearts", "diamonds", "clubs", "spades"]
    SUIT_ICONS = {
        "hearts": "♥",
        "diamonds": "♦",
        "clubs": "♣",
        "spades": "♠"
    }
    CARD_VALUE_DIGIT = {
        "jack": "J",
        "queen": "Q",
        "king": "K",
        "ace": "A"
    }
    SUIT_RANK = {
        "hearts": 4,
        "diamonds": 3,
        "clubs": 2,
        "spades": 1
    }
    ROUND_MULTIPLIERS = {1: 2, 2: 3, 3: 5, 4: 10}
    ROUND_DESCRIPTIONS = {
        1: "Guess the Color",
        2: "Higher or Lower",
        3: "Inside or Outside",
        4: "Guess the Suit"
    }
    CARD_IMAGES = {
         '10♣': 'https://i.postimg.cc/WpStn08H/10-of-clubs.png',
         '10♦': 'https://i.postimg.cc/kX4GhDhX/10-of-diamonds.png',
         '10♥': 'https://i.postimg.cc/m25kxR03/10-of-hearts.png',
         '10♠': 'https://i.postimg.cc/x1NCnh2w/10-of-spades.png',
         '2♣': 'https://i.postimg.cc/J0HgGNzz/2-of-clubs.png',
         '2♦': 'https://i.postimg.cc/7PCYgjCf/2-of-diamonds.png',
         '2♥': 'https://i.postimg.cc/PfBfKKZK/2-of-hearts.png',
         '2♠': 'https://i.postimg.cc/jdPx1N4T/2-of-spades.png',
         '3♣': 'https://i.postimg.cc/GmRLn2Xy/3-of-clubs.png',
         '3♦': 'https://i.postimg.cc/pLB2WHS1/3-of-diamonds.png',
         '3♥': 'https://i.postimg.cc/s2D31Ldf/3-of-hearts.png',
         '3♠': 'https://i.postimg.cc/8CKNvbNR/3-of-spades.png',
         '4♣': 'https://i.postimg.cc/ZRXm7K90/4-of-clubs.png',
         '4♦': 'https://i.postimg.cc/rmDcNtwv/4-of-diamonds.png',
         '4♥': 'https://i.postimg.cc/5yvVZdvg/4-of-hearts.png',
         '4♠': 'https://i.postimg.cc/gc6mwR5h/4-of-spades.png',
         '5♣': 'https://i.postimg.cc/zXZ5TvZc/5-of-clubs.png',
         '5♦': 'https://i.postimg.cc/X7fWLWn7/5-of-diamonds.png',
         '5♥': 'https://i.postimg.cc/t49jmcgd/5-of-hearts.png',
         '5♠': 'https://i.postimg.cc/XYxbMgZR/5-of-spades.png',
         '6♣': 'https://i.postimg.cc/Pqxkd8YP/6-of-clubs.png',
         '6♦': 'https://i.postimg.cc/YSsB0qz8/6-of-diamonds.png',
         '6♥': 'https://i.postimg.cc/QtKGTG6D/6-of-hearts.png',
         '6♠': 'https://i.postimg.cc/D0VVQjDX/6-of-spades.png',
         '7♣': 'https://i.postimg.cc/QCc2fgGn/7-of-clubs.png',
         '7♦': 'https://i.postimg.cc/G3Yn3R8J/7-of-diamonds.png',
         '7♥': 'https://i.postimg.cc/RVB5NYwr/7-of-hearts.png',
         '7♠': 'https://i.postimg.cc/ncG8711X/7-of-spades.png',
         '8♣': 'https://i.postimg.cc/2SksxBH2/8-of-clubs.png',
         '8♦': 'https://i.postimg.cc/NjdWCfSY/8-of-diamonds.png',
         '8♥': 'https://i.postimg.cc/mgPchhQ6/8-of-hearts.png',
         '8♠': 'https://i.postimg.cc/43tmbM26/8-of-spades.png',
         '9♣': 'https://i.postimg.cc/NMkFZXcL/9-of-clubs.png',
         '9♦': 'https://i.postimg.cc/QCNCDM8m/9-of-diamonds.png',
         '9♥': 'https://i.postimg.cc/d1YDWBgz/9-of-hearts.png',
         '9♠': 'https://i.postimg.cc/Vv76kc58/9-of-spades.png',
         'A♣': 'https://i.postimg.cc/FKtKRpF7/ace-of-clubs.png',
         'A♦': 'https://i.postimg.cc/bvQw2ndL/ace-of-diamonds.png',
         'A♥': 'https://i.postimg.cc/4dsNv39G/ace-of-hearts.png',
         'A♠': 'https://i.postimg.cc/L509MB04/ace-of-spades2.png',
         'J♣': 'https://i.postimg.cc/htmSHm8g/jack-of-clubs2.png',
         'J♦': 'https://i.postimg.cc/mrGbRrV9/jack-of-diamonds2.png',
         'J♥': 'https://i.postimg.cc/kMhqGsfq/jack-of-hearts2.png',
         'J♠': 'https://i.postimg.cc/SN2qM9v8/jack-of-spades2.png',
         'K♣': 'https://i.postimg.cc/LsTMp3Jd/king-of-clubs2.png',
         'K♦': 'https://i.postimg.cc/T3n6k6G3/king-of-diamonds2.png',
         'K♥': 'https://i.postimg.cc/gJ2bkLhx/king-of-hearts2.png',
         'K♠': 'https://i.postimg.cc/5yDh3PRz/king-of-spades2.png',
         'Q♣': 'https://i.postimg.cc/QxTGt3FJ/queen-of-clubs2.png',
         'Q♦': 'https://i.postimg.cc/rw26RPWX/queen-of-diamonds2.png',
         'Q♥': 'https://i.postimg.cc/vmXCj8Kb/queen-of-hearts2.png',
         'Q♠': 'https://i.postimg.cc/XXMPFrrc/queen-of-spades2.png',
         'joker': 'https://i.postimg.cc/HcbB3tr0/red-joker.png'
    }


    @app_commands.command(
        name='ridethebus',
        description="Test your luck in this high-risk card game! Progress through 4 rounds to multiply your bet up to 10x"
    )
    @app_commands.describe(
        bet="How many coins do you want to bet (10 - 500)"
    )
    async def ride_the_bus(self, interaction: discord.Interaction, bet: int):
        user_id = int(interaction.user.id)

        if bet < 10:
            return await interaction.response.send_message(
                "Minimum bet is 10 coins!",
                ephemeral=True
            )

        if bet > 500:
            return await interaction.response.send_message(
                "Maximum bet is 500 coins!",
                ephemeral=True
            )

        if user_id in self.games:
            return await interaction.response.send_message(
                "You already have a game in progress!",
                ephemeral=True
            )

        await interaction.response.defer()
        await self.start_game(interaction, bet)

    async def start_game(self, interaction: discord.Interaction, bet: int, message: discord.Message = None):
        user_id = int(interaction.user.id)
        balance = self.economy.get_balance(interaction.user.id)

        if bet > balance:
            return await interaction.followup.send(
                f"You don't have enough coins! Your balance: {balance}",
                ephemeral=True
            )

        self.economy.update_balance(interaction.user.id, -bet)
        self.games[user_id] = self.GameState(bet)
        if message:
            await self.play_round(interaction, user_id, message)
        else:
            msg = await self.play_round(interaction, user_id)
            self.games[user_id].message = msg

    async def play_round(self, interaction: discord.Interaction, user_id: int, message: discord.Message = None):
        game_state = self.games[user_id]
        embed = discord.Embed(
            title=f"Ride the Bus - Round {game_state.current_round}",
            color=0x5865F2
        )

        potential_multiplier = game_state.round_multipliers[game_state.current_round]
        potential_pot = game_state.bet * potential_multiplier

        win_prob = self.calculate_win_probability(game_state.current_round, game_state.cards)
        prob_meter = self.get_probability_meter(win_prob)

        embed.description = (
            f"**{self.ROUND_DESCRIPTIONS[game_state.current_round]}**\n"
            f"Potential Win: {potential_pot} coins ({potential_multiplier}x multiplier)\n"
            f"🎲 Win Probability: {prob_meter}"
        )

        view = self.GameView(self, user_id)

        if game_state.current_round == 1:
            embed.add_field(name="Choose:", value="Is the next card red or black?")
            view.add_item(ui.Button(style=discord.ButtonStyle.red, label="Red", custom_id="red"))
            view.add_item(ui.Button(style=discord.ButtonStyle.grey, label="Black", custom_id="black"))

        elif game_state.current_round == 2:
            embed.add_field(
                name="Choose:",
                value=f"Is the next card higher or lower than {self.card_to_str(game_state.cards[0])}?"
            )
            view.add_item(ui.Button(style=discord.ButtonStyle.green, label="Higher", custom_id="higher"))
            view.add_item(ui.Button(style=discord.ButtonStyle.red, label="Lower", custom_id="lower"))

        elif game_state.current_round == 3:
            card1, card2 = sorted(game_state.cards[:2], key=lambda x: self.CARD_VALUES.index(x[0]))
            embed.add_field(
                name="Choose:",
                value=f"Is the next card inside or outside {self.card_to_str(card1)}-{self.card_to_str(card2)}?"
            )
            view.add_item(ui.Button(style=discord.ButtonStyle.primary, label="Inside", custom_id="inside"))
            view.add_item(ui.Button(style=discord.ButtonStyle.primary, label="Outside", custom_id="outside"))

        elif game_state.current_round == 4:
            embed.add_field(name="Choose a suit:", value="What's the suit of the next card?")
            for suit in ["♥ Hearts", "♦ Diamonds", "♣ Clubs", "♠ Spades"]:
                view.add_item(ui.Button(
                    style=discord.ButtonStyle.secondary,
                    label=suit,
                    custom_id=suit.split()[0].strip()
                ))
        embed = self._add_common_embed_fields(embed, interaction, game_state)

        if message:
            await message.edit(embed=embed, view=view)
            view.message = message
            game_state.message = message
        else:
            if not interaction.response.is_done():
                await interaction.response.defer()

            try:
                if interaction.response.is_done():
                    message = await interaction.original_response()
                    await message.edit(embed=embed, view=view)
                else:
                    message = await interaction.edit_original_response(embed=embed, view=view)
                view.message = message
                game_state.message = message

            except discord.errors.NotFound:
                message = await interaction.followup.send(embed=embed, view=view)
                view.message = message
                game_state.message = message

        for item in view.children:
            if isinstance(item, ui.Button) and item.custom_id and item.label != "Cash Out":
                item.callback = self.create_button_callback(item.custom_id)

    async def handle_round(self, interaction: discord.Interaction, choice: str):
        """Process the player's choice"""
        user_id = interaction.user.id
        game_state = self.games[user_id]
        new_card = self.draw_card()
        game_state.cards.append(new_card)
        game_state.last_choice = choice

        won_round = self.check_round(game_state.current_round, choice, game_state.cards)
        print(f"Did you win the round? {won_round}")

        if won_round:
            if game_state.current_round < 4:
                game_state.update_pot()
                game_state.current_round += 1
                await self.play_round(interaction, user_id)
            else:
                await self.end_game(interaction, game_state, won=True)
        else:
            await self.end_game(interaction, game_state, won=False)

    def calculate_win_probability(self, round_num: int, cards: List[Tuple[str, str]]) -> float:
        """Calculate and return the probability of winning the current round"""
        if round_num == 1:  # Color round
            return 0.5

        elif round_num == 2:  # Higher/Lower
            current_value = cards[-1][0]
            current_index = self.CARD_VALUES.index(current_value)

            higher = len([v for v in self.CARD_VALUES if self.CARD_VALUES.index(v) > current_index])
            lower = len([v for v in self.CARD_VALUES if self.CARD_VALUES.index(v) < current_index])

            return min(1.0, max(higher, lower) / (len(self.CARD_VALUES) - 1))

        elif round_num == 3:  # Inside/Outside
            val1 = self.CARD_VALUES.index(cards[0][0])
            val2 = self.CARD_VALUES.index(cards[1][0])
            min_val, max_val = min(val1, val2), max(val1, val2)

            inside_cards = max_val - min_val - 1
            outside_cards = min_val + (len(self.CARD_VALUES) - 1 - max_val)

            return min(1.0, max(inside_cards, outside_cards) / (len(self.CARD_VALUES) - 2))

        elif round_num == 4:  # Suit
            return 0.25

        return 0.0

    def check_round(self, round_num: int, choice: str, cards: List[Tuple[str, str]]) -> bool:
        """Check if player's guess was correct for the current round"""
        current_card = cards[-1]
        print(f"Round Number: {round_num}")
        if round_num == 1:  # Color round
            is_red = current_card[1] in ["hearts", "diamonds"]
            return (choice == "red" and is_red) or (choice == "black" and not is_red)

        elif round_num == 2:  # Higher/Lower round
            prev_card = cards[-2]
            current_card = cards[-1]
            prev_index = self.CARD_VALUES.index(prev_card[0])
            current_index = self.CARD_VALUES.index(current_card[0])

            if current_index > prev_index:
                return choice == "higher"
            elif current_index < prev_index:
                return choice == "lower"
            else:
                prev_suit_rank = self.SUIT_RANK[prev_card[1]]
                current_suit_rank = self.SUIT_RANK[current_card[1]]
                if choice == "higher":
                    return current_suit_rank > prev_suit_rank
                else:
                    return current_suit_rank < prev_suit_rank

        elif round_num == 3:  # Inside/Outside round
            sorted_values = sorted([self.CARD_VALUES.index(cards[0][0]),
                                 self.CARD_VALUES.index(cards[1][0])])
            current_index = self.CARD_VALUES.index(current_card[0])

            if choice == "inside":
                return sorted_values[0] < current_index < sorted_values[1]
            elif choice == "outside":
                return current_index < sorted_values[0] or current_index > sorted_values[1]
            return False

        elif round_num == 4:  # Suit round
            suit_map = {
                '♥': 'hearts',
                '♦': 'diamonds',
                '♣': 'clubs',
                '♠': 'spades'
            }
            actual_suit = cards[-1][1]
            mapped_choice = suit_map.get(choice.lower())
            print(f"Actual Suit: {actual_suit.lower()}")
            print(f"Choice: {mapped_choice}")
            return mapped_choice == actual_suit.lower()

        return False

    def draw_card(self) -> Tuple[str, str]:
        new_card = random.choice(self.CARD_VALUES), random.choice(self.CARD_SUITS)
        return new_card

    def card_to_str(self, card: Tuple[str, str]) -> str:
        """Convert a card tuple to a display string"""
        value, suit = card
        return f"{value.capitalize()} {self.SUIT_ICONS.get(suit, '?')}"

    def get_probability_meter(self, probability: float) -> str:
        """Create a visual meter showing probability"""
        filled = '▰' * int(probability * 10)
        empty = '▱' * (10 - len(filled))
        return f"{filled}{empty} {probability * 100:.0f}%"

    async def end_game(self, interaction: discord.Interaction, game_state: GameState, won: Optional[bool] = None):
        """Handle game conclusion (win, loss, or cash out)"""
        user_id = interaction.user.id

        message_to_edit = None
        if user_id in self.games:
            message_to_edit = self.games[user_id].message
        try:
            message = interaction.message or await interaction.original_response()
        except:
            message = message_to_edit

        if message and message.embeds:
            embed = message.embeds[0]
            embed.color = 0x5865F2
            embed.clear_fields()
        else:
            embed = discord.Embed(color=0x5865F2)

        if game_state.cashed_out:
            embed.title = "💰 Cashed Out!"
            embed.description = f"You walked away with {game_state.pot} coins!"
            self.economy.update_balance(user_id, game_state.pot)
        elif won:
            embed.title = "🎉 You Won!"
            embed.description = f"Congratulations! You won {game_state.pot} coins!"
            self.economy.update_balance(user_id, game_state.pot)
        else:
            last_card = self.card_to_str(game_state.cards[-1])
            last_round = game_state.current_round
            current_card = game_state.cards[-1]

            choice = "🎲 Unknown! 🎲"
            if last_round == 1:
                choice = "Red" if game_state.last_choice == 'red' else "Black"
            elif last_round == 2:
                prev_card = game_state.cards[-2]
                choice = "Higher" if game_state.last_choice == 'higher' else "Lower"
                if self.CARD_VALUES.index(prev_card[0]) == self.CARD_VALUES.index(current_card[0]):
                    embed.description = (
                        f"The card was {last_card}\n"
                        f"You selected {choice}. Suits were compared ({current_card[1]} vs {prev_card[1]}).\n"
                        f"You lost your bet of {game_state.bet} coins."
                    )
            elif last_round == 3:
                choice = "Inside" if game_state.last_choice == 'inside' else "Outside"
            elif last_round == 4:
                suit_choice = game_state.last_choice
                choice = {
                    '♥': 'Hearts',
                    '♦': 'Diamonds',
                    '♣': 'Clubs',
                    '♠': 'Spades'
                }.get(suit_choice)

            embed.title = "💔 Game Over"
            embed.description = (
                f"The card was {last_card}. You selected {choice}.\n"
                f"You lost your bet of {game_state.bet} coins."
            )

        if game_state.cards:
            card_display = "\n".join(
                [f"Round {i + 1}: {self.card_to_str(card)}" for i, card in enumerate(game_state.cards)])
            embed.add_field(name="Cards Drawn", value=card_display, inline=False)

        embed = self._add_common_embed_fields(embed, interaction, game_state)

        view = self.PlayAgainView(self, user_id, game_state.bet)

        try:
            if message:
                await message.edit(embed=embed, view=view)
            elif not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, view=view)
            else:
                await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            print(f"Error updating end game message: {e}")

        if user_id in self.games:
            del self.games[user_id]


async def setup(bot: commands.Bot):
    economy_utils = EconomyUtils()
    await bot.add_cog(
        RideTheBus(bot, economy_utils),
        guilds=[
            discord.Object(id=771099589713199145),
            discord.Object(id=601677205445279744)
        ]
    )
