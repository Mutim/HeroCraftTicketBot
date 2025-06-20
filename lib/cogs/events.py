
import discord
from discord.ext import commands
import config


# Main cog class
class Events(commands.Cog, name="events"):
    def __init__(self, bot):
        self.bot = bot

    """
    Events monitoring for HeroCraft
    """

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        print(f"{guild.name} - {guild.id}")
        if guild.id == 601677205445279744:
            print('Member in HC discord')
            welcome_channel = self.bot.get_channel(1239400896752914474)
        else:
            print("Member not in HC Discord")
            return

        embed = discord.Embed(
            title=f"HeroCraft Welcomes You!",
            description=f"As you step through the grand gates of our enchanted kingdom, may you find, epic tales, and endless adventures within our hallowed halls {member.mention}. Whether you are a valiant knight, a wise mage, a cunning rogue, or a humble bard, your presence adds to the rich tapestry of our story.\n\n<:purple_arrow:1249559669647740959> **Prepare yourself for quests and challenges** that will test your might and wits\n<:purple_arrow:1249559669647740959> **Engage in lively tavern banter** with fellow travelers and forge alliances.\n<:purple_arrow:1249559669647740959> **Delve into the archives** of our knowledge to enhance your skills and wisdom.\n\nBe thou vigilant of the rules and traditions that govern our land, and may your journey here be filled with glory and honor.",
            color=0x00eeff)
        embed.set_thumbnail(url=member.avatar)
        embed.set_author(name="Herocraft Welcome Bot")

        dm_embed = discord.Embed(
            title="Welcome to HeroCraft!",
            description=f"As you step through the grand gates of our enchanted kingdom, may you find, epic tales, and "
                        f"endless adventures within our hallowed halls {member.mention}. Whether you are a valiant "
                        f"knight, a wise mage, a cunning rogue, or a humble bard, your presence adds to the rich "
                        f"tapestry of our story.\n\n<:purple_arrow:1249559669647740959> **Prepare yourself for quests "
                        f"and challenges** that will test your might and wits"
                        f"\n<:purple_arrow:1249559669647740959> "
                        f"**Engage in lively tavern banter** with fellow travelers and forge alliances."
                        f"\n<:purple_arrow:1249559669647740959> **Delve into the archives** of our knowledge to enhance your skills and wisdom."
                        f"\n\nBe thou vigilant of the rules and traditions that govern our land, and may your journey here be filled with glory and honor."
                        f"\nIn case you lose your invite, you can **__[rejoin here!](https://discord.gg/c6P9Z2Vxsz)__**",
            color=0x00eeff)
        dm_embed.set_thumbnail(url=guild.icon.url)

        try:
            await member.send(embed=dm_embed)
            print(f"Sent welcome DM to {member.name}")
        except discord.Forbidden:
            print(f"Could not send DM to {member.name} (DM's closed or no permission)")
        except exception as e:
            print(f"Error sending DM to {member.name}: {e}")

        await welcome_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        print(f"{guild.name} - {guild.id}: {member.name} has left!")
        if guild.id == 601677205445279744:
            print('Member in HC discord')
            leave_channel = self.bot.get_channel(1239400896752914474)
        else:
            print("Member not in HC Discord")
            return
        if leave_channel:
            embed = discord.Embed(
                title="A Hero has Departed!",
                description=f"{member.mention} ({member.name}) has left.",
                color="0xff0000"
            )
            embed.set_thumbnail(url=member.avatar)
            embed.set_footer(text=f"Member count: {guild.member_count}")

            try:
                await leave_channel.send(embed=embed)
                print(f"Leave message sent for {member.name}")
            except Exception as e:
                print(f"Failed to send goodbye message: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(
        Events(bot),
        guilds=[
            discord.Object(id=601677205445279744),
            discord.Object(id=771099589713199145)
        ]
    )
