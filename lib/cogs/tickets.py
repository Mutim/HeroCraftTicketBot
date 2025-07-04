import traceback
import discord
import config
import time
import datetime
import uuid
from discord import app_commands, ui
from discord.ui import View
from discord.ext import commands

# TODO: Add button to tickets channel that calls the TicketView() class.


class ButtonView(View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Claim Ticket [Staff]",
        style=discord.ButtonStyle.green,
        emoji="☑️",
        custom_id="0")
    async def claim_callback(self, itx: discord.Interaction, button):
        button.disabled = True
        button.emoji = "☑️"
        button.label = f"Claimed by {itx.user}"

        overwrites = discord.PermissionOverwrite(
            manage_messages=True,
            read_messages=True,
            add_reactions=True,
            read_message_history=True,
            send_messages=True,
            use_application_commands=False,
            attach_files=True)

        await itx.channel.set_permissions(itx.user, overwrite=overwrites)
        await itx.response.edit_message(view=self)

    async def interaction_check(self, interaction):
        role_ids = [992669093545136189, 992671194186780732,
                    992671391289704468, 992675253736198284]
        for role_id in role_ids:
            if interaction.user.get_role(role_id):
                return True
            else:
                interaction.response.send_message(
                    "Only a member of staff may claim a ticket.")
                return False

    @discord.ui.button(
        label="Close Ticket [Staff]",
        style=discord.ButtonStyle.danger,
        emoji="<:open_lock:965662978588413972>",
        custom_id="1")
    async def close_callback(self, itx: discord.Interaction, button):

        role_ids = [992669093545136189, 992671194186780732,
                    992671391289704468, 992675253736198284]
        member = itx.user
        for role_id in role_ids:
            if member.get_role(role_id):
                await itx.response.send_modal(
                    TicketReason(
                        ticket_name=itx.channel.name,
                        admin_name=itx.user,
                        channel=itx.channel
                    )
                )
            else:
                itx.response.send_message("Only a member of staff may lock a ticket.")


class TicketView(View):
    @discord.ui.select(
        min_values=1,
        max_values=1,
        placeholder="Select a Ticket Category",
        options=[
            discord.SelectOption(
                    label='Bug',
                    value="Bug",
                    emoji='🐛',
                    description='Server related issue'),
            discord.SelectOption(
                label='Player',
                value="Player",
                emoji='🧑‍🤝‍🧑',
                description='Player conduct issues'),
            discord.SelectOption(
                label='Store',
                value="Store",
                emoji='🏪',
                description='Purchase related issues'),
            discord.SelectOption(
                label='Appeal',
                value="Appeal",
                emoji='<:banhammer:996549617506324632>',
                description='Ban Appeal. Ban # is needed.'),
            discord.SelectOption(
                label='Staff',
                value="Staff",
                emoji='🧑‍💼',
                description='Staff related issues. (This will go to Admins, and Sr. Moderators)'),
            discord.SelectOption(
                label='Other',
                value="Other",
                emoji='<:other_left:747195307925831710>',
                description='Other issues not specified.')
        ],)
    async def select_callback(self, itx: discord.Interaction, select: discord.ui.Select):
        select.disabled = True
        label = select.values[0]
        await itx.response.send_modal(TicketForm(ticket_name=label))
        await TicketForm(ticket_name=label).wait()
        await itx.edit_original_response(view=None)


class TicketForm(ui.Modal, title="Submit your Ticket"):

    def __init__(self, ticket_name: str):
        super(TicketForm, self).__init__(timeout=None)
        self.ticket_name = ticket_name

    ign = ui.TextInput(
        label="What is Your In-Game Name?",
        style=discord.TextStyle.short,
        placeholder="ex: Notch",
        max_length=25,
        required=True)
    issue = ui.TextInput(
        label="Describe Your Issue",
        style=discord.TextStyle.paragraph,
        placeholder="Be as descriptive as possible",
        max_length=1000,
        required=True)
    recreate = ui.TextInput(
        label="Steps to Recreate the Issue",
        style=discord.TextStyle.paragraph,
        placeholder="Step-by-Step Instructions (if applicable)",
        max_length=1000,
        required=True)

    async def on_submit(self, itx: discord.Interaction):
        ticket_number = uuid.uuid1()
        role_ping = {
            "Bug": "992669093545136189",
            "Player": "992669093545136189",
            "Store": "992671194186780732",
            "Appeal": "992671194186780732",
            "Staff": "992671391289704468",
            "Other": "992671391289704468"
        }

        dynamic_role = itx.user.guild.get_role(
            int(role_ping[self.ticket_name]))
        # Staff roles in order:          Mod Management, Sr Mod, Mod, Helper, Dev

        staff_roles = [992669093545136189, 992671194186780732,
                       992671391289704468, 771099590032097343]

        new_overwrites = {}

        view_roles = []
        try:
            for role in staff_roles:
                if itx.guild.get_role(role):
                    view_roles.append(f"<@&{role}>")
        except AttributeError as err:
            print(err)

        embed = discord.Embed(
            title=f"<:support_ticket:996549597042315375> Support Ticket - [{self.ticket_name}]",
            description=f"Thank you for opening a support ticket, {itx.user}.\n"
                        f"A member <@&{role_ping[self.ticket_name]}> will be available to help you shortly.\n"
                        f"These roles have access to view this ticket: {view_roles}",
            color=config.success)
        embed.add_field(
            name=f"Submitter ", value=f"Discord: {itx.user} | IGN: {self.ign}", inline=False)
        embed.add_field(name=f"Issue:", value=f"{self.issue}\n", inline=False)
        embed.add_field(name=f'How to Recreate:', value=f'{self.recreate}\n', inline=False)
        embed.set_footer(
            text=f"User ID: {itx.user.id} | Ticket Number • {ticket_number}")

        for role in staff_roles:
            appended_role = itx.user.guild.get_role(int(role))

            new_overwrites.update({appended_role: discord.PermissionOverwrite(
                read_messages=True,
                add_reactions=True,
                read_message_history=True,
                send_messages=True,
                use_application_commands=False,
                attach_files=True,
            )})

        overwrites = {
            itx.client.get_guild(601677205445279744).default_role: discord.PermissionOverwrite(read_messages=False),
            itx.client.get_guild(601677205445279744).me: discord.PermissionOverwrite(read_messages=True),
            # User roles
            itx.user: discord.PermissionOverwrite(
                read_messages=True,
                add_reactions=True,
                read_message_history=True,
                send_messages=True,
                use_application_commands=False,
                attach_files=True),
            # # Staff roles
            # dynamic_role: discord.PermissionOverwrite(
            #     read_messages=True,
            #     add_reactions=True,
            #     read_message_history=True,
            #     send_messages=True,
            #     use_application_commands=False,
            #     attach_files=True,
            # )
        }
        channel = itx.client.get_guild(601677205445279744).get_channel(985201287488499752)
        print(channel)
        channel_text = await itx.client.get_guild(601677205445279744).get_channel(985201287488499752).create_text_channel(
            f'{self.ticket_name.lower()} Ticket - {itx.user.name}', overwrites=overwrites)
        await itx.response.send_message(f"Your ticket has been created at {channel_text.mention}!", ephemeral=True)

        channel = itx.client.get_guild(601677205445279744).get_channel(channel_text.id)

        message = await channel.send(
            content=f"The <@&{role_ping[self.ticket_name]}> team has been notified, {itx.user}.",
            embed=embed,
            view=ButtonView())
        await message.pin(reason="User Created Ticket")


class TicketReason(ui.Modal, title="Reason for Closing Ticket"):

    def __init__(self, ticket_name, admin_name, channel):
        super(TicketReason, self).__init__(timeout=None)
        self.ticket_name = ticket_name
        self.admin_name = admin_name
        self.channel = channel

    reason = ui.TextInput(
        label="Describe the Reason for Closure",
        style=discord.TextStyle.paragraph,
        placeholder="Please give a detailed description",
        max_length=1000,
        required=True)

    async def on_submit(self, itx: discord.Interaction):
        embed = discord.Embed(
            title=f"<:support_ticket:996549597042315375> Support Ticket Closed - [{self.ticket_name}]",
            description=f"Ticket has been successfully closed by {self.admin_name}",
            color=config.success)
        embed.add_field(name=f"Reason", value=f"{self.reason}", inline=False)
        embed.set_footer(
            text=f"User ID: {itx.user.id} | iID:  • {time.ctime(time.time())}")

        admin_channel = itx.client.get_channel(743476824763269150)
        try:
            await itx.response.defer()
            await admin_channel.send(embed=embed)
            await self.channel.delete()
        except Exception as err:
            print(err)
            traceback.print_exc()


class Tickets(commands.Cog, name="ticket"):
    def __init__(self, bot):
        self.bot = bot
    """
    Ticket Class. Takes input from TicketForm() and TicketView().
    
    Sends the user a drop-down menu so they can select their issue category. When they select their category, 
    they will get a TicketForm. 
    
    This info is sent to logs, and a ticket channel with '{user.name}-ticket'
    
    Make a ticket.
    """

    @app_commands.checks.cooldown(1, 600.0, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.command(
        name="ticket",
        description="Create a support ticket.")
    async def ticket(
            self,
            itx: discord.Interaction):
        """
        Ticket
        """

        async def interaction_check(interaction) -> bool:
            member = interaction.user
            if not member.get_role(1007407892925788260):
                return True
            else:
                interaction.response.send_message(
                    "You cannot open a ticket. If you believe this is in error, please contact a moderator.",
                    ephimeral=True)
                return False
        if await interaction_check(itx):
            try:
                view = TicketView()
                await itx.response.send_message(
                    "Select the proper category for your ticket. If you're unsure, select 'Other'",
                    ephemeral=True, view=view)
            except Exception as err:
                traceback.format_exc()
                await itx.response.send_message(f'An error has occurred: {err}')


async def setup(bot: commands.Bot):
    await bot.add_cog(
        Tickets(bot),
        guilds=[
            discord.Object(id=771099589713199145),
            discord.Object(id=601677205445279744)
        ]
    )
