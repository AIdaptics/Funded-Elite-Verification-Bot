import sys
import subprocess
import pkg_resources
from datetime import datetime, timezone, timedelta
import logging
import discord
from discord.ext import commands
import asyncio
from dotenv import load_dotenv
import os
from typing import Dict, List
import json
from discord.ui import View

def check_and_install_requirements():
    try:
        # Read requirements from file
        with open('requirements.txt') as f:
            requirements = [line.strip() for line in f if line.strip()]
        
        # Check installed packages
        installed = {pkg.key for pkg in pkg_resources.working_set}
        missing = []
        
        for requirement in requirements:
            pkg_name = requirement.split('>=')[0]
            if pkg_name.lower() not in installed:
                missing.append(requirement)
        
        if missing:
            print("Installing missing packages...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + missing)
            print("All required packages installed successfully!")
        else:
            print("All required packages already installed!")
            
    except Exception as e:
        print(f"Error checking/installing packages: {e}")
        sys.exit(1)

# Run the check at startup
check_and_install_requirements()



# Load environment variables
load_dotenv()

# Bot configuration from .env
TOKEN = os.getenv('TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))
WELCOME_CHANNEL_ID = int(os.getenv('WELCOME_CHANNEL_ID'))
CALENDAR_LINK = os.getenv('CALENDY_LINK')
COMPANY_LOGO = "https://cdn.discordapp.com/attachments/1335112843476860968/1366511856994222201/funded.jpg"
# Set up intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.guild_messages = True

bot = commands.Bot(command_prefix='!', intents=intents)



# Set up logging
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_time_remaining(end_time):
    remaining = end_time - datetime.now()
    hours = remaining.seconds // 3600
    minutes = (remaining.seconds // 60) % 60
    return f"{hours}h {minutes}m remaining"



# Constants for message storage
WELCOME_MESSAGE_FILE = 'welcome_message.json'

def save_welcome_message(message_id, channel_id):
    data = {'message_id': message_id, 'channel_id': channel_id}
    with open(WELCOME_MESSAGE_FILE, 'w') as f:
        json.dump(data, f)

class VerificationView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Start Verification",
        style=discord.ButtonStyle.green,
        custom_id="verify_button",
        emoji="🔒"
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.Button):
        # 1️⃣ Defer immediately (ephemeral)
        await interaction.response.defer(ephemeral=True)

        # 2️⃣ Check if user already has any of the paid/free roles and is not muted
        paid_free = {
            int(os.getenv('AARON_PAID_ROLE_ID')),
            int(os.getenv('AARON_FREE_ROLE_ID')),
            int(os.getenv('ILLYA_PAID_ROLE_ID')),
            int(os.getenv('ILLYA_FREE_ROLE_ID'))
        }
        muted = int(os.getenv('ROLE_MUTED_ID'))
        user_roles = {r.id for r in interaction.user.roles}

        if user_roles & paid_free and muted not in user_roles:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="✅ Already Verified",
                    description="You have already completed the verification process!",
                    color=discord.Color.green()
                ),
                ephemeral=True
            )

        # 3️⃣ Prevent duplicate tickets
        ticket_name = f"verify-{interaction.user.name.lower()}"
        existing = discord.utils.get(interaction.guild.channels, name=ticket_name)
        if existing:
            close_ts = int((datetime.now(timezone.utc) + timedelta(seconds=20)).timestamp())
            await interaction.followup.send(
                embed=discord.Embed(
                    title="🎫 Active Ticket Found",
                    description=(
                        f"You already have an active ticket: {existing.mention}\n"
                        f"This ticket will auto-close <t:{close_ts}:R>"
                    ),
                    color=discord.Color.yellow()
                ),
                ephemeral=True
            )
            # schedule deletion in 20s
            await asyncio.sleep(20)
            try:
                await existing.delete()
                logging.info(f"Deleted duplicate ticket for {interaction.user}")
            except Exception as e:
                logging.warning(f"Could not delete duplicate ticket: {e}")
            return

        # 4️⃣ Create the ticket channel under same category
        ticket_channel = await interaction.guild.create_text_channel(
            name=ticket_name,
            category=interaction.channel.category  # same category as the button
        )  # :contentReference[oaicite:1]{index=1}

        # 5️⃣ Lock it down: only the user can see/send
        await ticket_channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
        await ticket_channel.set_permissions(interaction.guild.default_role, read_messages=False)
        # :contentReference[oaicite:2]{index=2}

        # 7️⃣ Send the welcome embed with booking CTA
        expiry = datetime.now(timezone.utc) + timedelta(hours=24)
        exp_ts = int(expiry.timestamp())
        embed = discord.Embed(
            title="🎉 Welcome to Your Verification Process!",
            description=(
                "To complete your verification and gain access to the server, please follow these steps:\n\n"
                f"**1.** Book your onboarding call here: [Calendly]({os.getenv('CALENDLY_LINK')})\n"
                "**2.** After booking, click the 'I Have Booked' button below\n\n"
                f"**Note:** This ticket closes <t:{exp_ts}:R>"
            ),
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=os.getenv('COMPANY_LOGO'))
        embed.add_field(name="📅 Booking Status", value="Pending", inline=True)
        embed.add_field(name="⏱️ Expires", value=f"<t:{exp_ts}:f>", inline=True)
        embed.set_footer(text=f"User ID: {interaction.user.id}")

        await ticket_channel.send(
            f"Welcome {interaction.user.mention}! Let's get you verified.",
            embed=embed,
            view=ConfirmBookingView(interaction.user)
        )

        # 8️⃣ Auto-close after 24 h
        async def auto_close():
            await asyncio.sleep(86400)
            try:
                await ticket_channel.delete()
                logging.info(f"Auto-closed ticket for {interaction.user}")
            except Exception:
                pass

        asyncio.create_task(auto_close())

        # 9️⃣ Let them know
        await interaction.followup.send(
            f"✅ Your ticket is ready: {ticket_channel.mention}",
            ephemeral=True
        )
member_original_roles: Dict[int, List[discord.Role]] = {}

@bot.event
async def on_member_join(member):
    try:
        # Store original roles
        member_original_roles[member.id] = [role for role in member.roles if role != member.guild.default_role]
        
        # Remove all roles except @everyone
        await member.remove_roles(*[role for role in member.roles if role != member.guild.default_role])
        
        # Add muted role
        muted_role = member.guild.get_role(int(os.getenv('ROLE_MUTED_ID')))
        if muted_role:
            await member.add_roles(muted_role)
            logging.info(f"Added muted role to {member.name} ({member.id})")
        else:
            logging.error(f"Muted role not found for {member.name} ({member.id})")
            
    except Exception as e:
        logging.error(f"Error in on_member_join for {member.name}: {e}")

class ConfirmBookingView(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(label="I Have Booked", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Validate role ID before converting to int
        muted_role_id = os.getenv('ROLE_MUTED_ID')
        if not muted_role_id:
            logging.error("ROLE_MUTED_ID not found in environment variables")
            return await interaction.followup.send('❌ Configuration error: Muted role ID not set', ephemeral=True)
        
        # Get muted role
        muted_role = interaction.guild.get_role(int(muted_role_id))
        if not muted_role:
            logging.error(f"Muted role with ID {muted_role_id} not found in guild")
            return await interaction.followup.send('❌ Muted role not found', ephemeral=True)

        try:
            # Remove muted role first
            await interaction.user.remove_roles(muted_role)
            logging.info(f"Removed muted role from {interaction.user.name}")
            
            # Restore original roles if they exist
            if interaction.user.id in member_original_roles:
                original_roles = member_original_roles[interaction.user.id]
                if original_roles:
                    await interaction.user.add_roles(*original_roles)
                    logging.info(f"Restored roles for {interaction.user.name}: {[role.name for role in original_roles]}")
                del member_original_roles[interaction.user.id]
            
            await interaction.followup.send("✅ Verification complete! Your roles have been restored.", ephemeral=True)
            
            # Close ticket channel
            await asyncio.sleep(5)
            await interaction.channel.delete()
            logging.info(f"Closed verification ticket for {interaction.user.name}")
            
        except discord.Forbidden:
            logging.error(f"Permission error during role restoration for {interaction.user.name}")
            await interaction.followup.send("❌ Bot lacks required permissions", ephemeral=True)
        except Exception as e:
            logging.error(f"Error in verification process for {interaction.user.name}: {e}")
            await interaction.followup.send("❌ Error during verification", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")
    await bot.change_presence(status=discord.Status.dnd)
    
    # Get specific guild
    guild = bot.get_guild(1324606547116032102)
    if guild:
        welcome_channel = discord.utils.get(guild.channels, name="welcome-verify")
        if welcome_channel:
            # Clean up only bot's previous messages
            try:
                async for message in welcome_channel.history(limit=100):
                    if message.author == bot.user:
                        await message.delete()
                logging.info(f"Cleaned up bot's previous messages in welcome channel")
            except Exception as e:
                logging.error(f"Error cleaning welcome channel: {e}")
            
            # Create new welcome embed
            embed = discord.Embed(
                title="👋 Welcome to the Server!",
                description=(
                    "To access the server, you'll need to complete our verification process.\n\n"
                    "**What to expect:**\n"
                    "• Create a verification ticket\n"
                    "• Schedule a quick onboarding call\n"
                    "• Confirm your booking\n"
                    "• Get verified and gain access!\n\n"
                    "Click the button below to begin."
                ),
                color=0x5865F2
            )
            embed.set_footer(text="Join our community today!")
            embed.set_thumbnail(url=COMPANY_LOGO)
            
            message = await welcome_channel.send(embed=embed, view=VerificationView())
            save_welcome_message(message.id, welcome_channel.id)
            logging.info(f"Created new welcome message: {message.jump_url}")

@bot.event
async def setup_guild_permissions(guild):
    everyone_role = guild.default_role
    muted_role = guild.get_role(int(os.getenv('ROLE_MUTED_ID')))
    
    for channel in guild.channels:
        if channel.name == "welcome-verify":
            await channel.set_permissions(everyone_role, view_channel=True, send_messages=False)
            if muted_role:
                await channel.set_permissions(muted_role, view_channel=True, send_messages=False)
        else:
            await channel.set_permissions(everyone_role, view_channel=False)
            if muted_role:
                await channel.set_permissions(muted_role, view_channel=False)

bot.run(TOKEN)