import discord
from discord.ext import commands
from discord.ui import Button, View, Select
import json
import os
import asyncio
from datetime import datetime

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Load bad words from files
def load_bad_words(language):
    try:
        with open(f'bad_words_{language}.txt', 'r') as f:
            return [line.strip().lower() for line in f.readlines()]
    except FileNotFoundError:
        print(f"Warning: bad_words_{language}.txt not found")
        return []

english_bad_words = load_bad_words('english')
hinglish_bad_words = load_bad_words('hinglish')

# Load configuration
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    config = {
        "staff_role_id": 1322182468845174816,
        "log_channel_id": 1418133063623508082,
        "ticket_category_id": 1419562664023035904,
        "support_channel_id": 1347744654136971428,
        "transcript_channel_id": 1418902601327575081,
        "ticket_counters": {}
    }
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)

# Save configuration
def save_config():
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)

# Get next ticket number
def get_next_ticket_number(ticket_type):
    if ticket_type not in config["ticket_counters"]:
        config["ticket_counters"][ticket_type] = 1
    else:
        config["ticket_counters"][ticket_type] += 1
    save_config()
    return config["ticket_counters"][ticket_type]

# Ticket close view with options
class CloseTicketView(View):
    def __init__(self, ticket_owner_id):
        super().__init__(timeout=None)
        self.ticket_owner_id = ticket_owner_id
    
    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, emoji="🔒", custom_id="close_ticket")
    async def close_ticket(self, interaction, button):
        # Check if user is ticket owner or has mod permissions
        if interaction.user.id != self.ticket_owner_id and not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Only the ticket owner or staff can close this ticket.", ephemeral=True)
            return
        
        # Create options view
        options_view = TicketOptionsView(interaction.channel, self.ticket_owner_id)
        await interaction.response.send_message("Ticket closed. What would you like to do?", view=options_view, ephemeral=False)
        
        # Disable the close button
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

# Ticket options view (reopen, delete, transcript)
class TicketOptionsView(View):
    def __init__(self, channel, ticket_owner_id):
        super().__init__(timeout=None)
        self.channel = channel
        self.ticket_owner_id = ticket_owner_id
    
    @discord.ui.button(label="Reopen", style=discord.ButtonStyle.green, emoji="🔓", custom_id="reopen_ticket")
    async def reopen_ticket(self, interaction, button):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Only staff can reopen tickets.", ephemeral=True)
            return
        
        # Re-enable the close button in the original message
        original_message = None
        async for message in self.channel.history():
            if message.components:  # Message with components (buttons)
                original_message = message
                break
        
        if original_message:
            view = CloseTicketView(self.ticket_owner_id)
            await original_message.edit(view=view)
        
        await interaction.response.edit_message(content="Ticket reopened!", view=None)
    
    @discord.ui.button(label="Delete", style=discord.ButtonStyle.red, emoji="🗑️", custom_id="delete_ticket")
    async def delete_ticket(self, interaction, button):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Only staff can delete tickets.", ephemeral=True)
            return
        
        await interaction.response.edit_message(content="Deleting ticket in 5 seconds...", view=None)
        await asyncio.sleep(5)
        await self.channel.delete()
    
    @discord.ui.button(label="Transcript", style=discord.ButtonStyle.blurple, emoji="📝", custom_id="save_transcript")
    async def save_transcript(self, interaction, button):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Only staff can save transcripts.", ephemeral=True)
            return
        
        await interaction.response.send_message("Creating transcript...", ephemeral=True)
        
        # Create transcript content
        transcript_content = f"Transcript for {self.channel.name}\nCreated: {self.channel.created_at}\n\n"
        
        async for message in self.channel.history(oldest_first=True):
            transcript_content += f"{message.created_at} - {message.author.display_name}: {message.content}\n"
            if message.attachments:
                transcript_content += f"Attachments: {', '.join([a.url for a in message.attachments])}\n"
            transcript_content += "\n"
        
        # Send transcript to transcript channel
        transcript_channel = bot.get_channel(config["transcript_channel_id"])
        if transcript_channel:
            # Split transcript if too long
            if len(transcript_content) > 2000:
                # Split into chunks
                chunks = [transcript_content[i:i+2000] for i in range(0, len(transcript_content), 2000)]
                for chunk in chunks:
                    await transcript_channel.send(f"```{chunk}```")
            else:
                await transcript_channel.send(f"```{transcript_content}```")
            
            await interaction.followup.send("Transcript saved!", ephemeral=True)
        else:
            await interaction.followup.send("Transcript channel not found!", ephemeral=True)

# Ticket system
class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.select(
        placeholder="Select ticket type",
        options=[
            discord.SelectOption(label="Partnership", value="partnership", emoji="🤝"),
            discord.SelectOption(label="Support", value="support", emoji="🛠️"),
            discord.SelectOption(label="Bug Report", value="bug", emoji="🐛"),
            discord.SelectOption(label="Have Issue", value="issue", emoji="❓"),
            discord.SelectOption(label="Won Giveaway", value="giveaway", emoji="🎉"),
            discord.SelectOption(label="Report Player", value="report", emoji="🚨")
        ],
        custom_id="ticket_type_select"
    )
    async def select_callback(self, interaction, select):
        ticket_type = select.values[0]
        await create_ticket(interaction, ticket_type)

async def create_ticket(interaction, ticket_type):
    category = bot.get_channel(config["ticket_category_id"])
    if not category:
        await interaction.response.send_message("Ticket category not configured. Please contact an admin.", ephemeral=True)
        return
    
    # Get next ticket number and create channel name
    ticket_number = get_next_ticket_number(ticket_type)
    channel_name = f"{ticket_type}-{ticket_number}"
    
    # Get staff role mention
    staff_mention = ""
    if config["staff_role_id"]:
        staff_role = interaction.guild.get_role(config["staff_role_id"])
        if staff_role:
            staff_mention = staff_role.mention
    
    # Create ticket channel
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    
    # Add staff role if configured
    if config["staff_role_id"]:
        staff_role = interaction.guild.get_role(config["staff_role_id"])
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    
    ticket_channel = await category.create_text_channel(
        name=channel_name,
        overwrites=overwrites
    )
    
    # Send initial message with close button
    embed = discord.Embed(
        title=f"{ticket_type.capitalize()} Ticket #{ticket_number}",
        description=f"Hello {interaction.user.mention}! A staff member will be with you shortly.\n\n**Staff will be notified:** {staff_mention}",
        color=discord.Color.blue()
    )
    
    if ticket_type == "report":
        embed.add_field(
            name="Player Report", 
            value="Please provide:\n- Player's username\n- What they did\n- When it happened\n- Any evidence (screenshots/videos)",
            inline=False
        )
    else:
        embed.add_field(
            name="Important", 
            value="Please provide all relevant information to help us assist you faster.",
            inline=False
        )
    
    embed.set_footer(text="Staff will be with you shortly.")
    
    close_view = CloseTicketView(interaction.user.id)
    await ticket_channel.send(embed=embed, view=close_view)
    
    # Mention staff role in the ticket
    if staff_mention:
        await ticket_channel.send(f"{staff_mention} New ticket created!")
    
    await interaction.response.send_message(f"Ticket created: {ticket_channel.mention}", ephemeral=True)
    
    # Log ticket creation
    log_channel = bot.get_channel(config["log_channel_id"])
    if log_channel:
        log_embed = discord.Embed(
            title="Ticket Created",
            description=f"**User:** {interaction.user.mention}\n**Type:** {ticket_type}\n**Channel:** {ticket_channel.mention}",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        await log_channel.send(embed=log_embed)

# Events
@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    # Add persistent views
    bot.add_view(TicketView())
    bot.add_view(CloseTicketView(0))
    
    # Set bot status
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Raimc Server"))

@bot.event
async def on_message(message):
    # Ignore messages from bots
    if message.author.bot:
        return
    
    # Check for bad words
    content = message.content.lower()
    
    # Check English bad words
    english_violations = [word for word in english_bad_words if word in content]
    
    # Check Hinglish bad words
    hinglish_violations = [word for word in hinglish_bad_words if word in content]
    
    if english_violations or hinglish_violations:
        # Delete the message
        await message.delete()
        
        # Warn the user
        warning_msg = f"{message.author.mention}, please avoid using inappropriate language in this server."
        await message.channel.send(warning_msg, delete_after=10)
        
        # Log the violation
        log_channel = bot.get_channel(config["log_channel_id"])
        if log_channel:
            embed = discord.Embed(
                title="Language Violation",
                description=f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            
            if english_violations:
                embed.add_field(name="English Violations", value=", ".join(english_violations), inline=False)
            if hinglish_violations:
                embed.add_field(name="Hinglish Violations", value=", ".join(hinglish_violations), inline=False)
                
            embed.add_field(name="Message Content", value=f"||{message.content}||", inline=False)
            
            await log_channel.send(embed=embed)
    
    # Process commands
    await bot.process_commands(message)

# Commands
@bot.command()
@commands.has_permissions(administrator=True)
async def setup_tickets(ctx):
    """Setup the ticket system in the current channel"""
    embed = discord.Embed(
        title="Support Tickets",
        description="**Need Help? Please Read Carefully**\n\n- Click the button that best matches the type of support you need.\n- Provide a clear and detailed description of your issue.\n- Missing or vague information may cause delays.\n- Include any relevant details like error messages or steps to reproduce.\n- Repeated spam or unnecessary pinging of staff may lead to a timeout.\n\n**Note:** Only memberships from the **GamerFleet** YouTube channel are valid. Memberships from other channels will not be considered.\n\n**Thank you for helping us help you!**",
        color=discord.Color.blue()
    )
    
    view = TicketView()
    await ctx.send(embed=embed, view=view)
    
    # Update config
    config["support_channel_id"] = ctx.channel.id
    save_config()
    
    await ctx.message.delete()

@bot.command()
@commands.has_permissions(administrator=True)
async def set_staff_role(ctx, role: discord.Role):
    """Set the staff role for tickets"""
    config["staff_role_id"] = role.id
    save_config()
    await ctx.send(f"Staff role set to {role.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_log_channel(ctx, channel: discord.TextChannel):
    """Set the log channel for moderation actions"""
    config["log_channel_id"] = channel.id
    save_config()
    await ctx.send(f"Log channel set to {channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_ticket_category(ctx, category: discord.CategoryChannel):
    """Set the category where tickets will be created"""
    config["ticket_category_id"] = category.id
    save_config()
    await ctx.send(f"Ticket category set to {category.name}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_transcript_channel(ctx, channel: discord.TextChannel):
    """Set the transcript channel"""
    config["transcript_channel_id"] = channel.id
    save_config()
    await ctx.send(f"Transcript channel set to {channel.mention}")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def close(ctx):
    """Close a ticket"""
    if "ticket" in ctx.channel.name or any(x in ctx.channel.name for x in ["support", "bug", "issue", "giveaway", "report", "partnership"]):
        # Find the close button message
        close_message = None
        async for message in ctx.channel.history():
            if message.components:  # Message with components (buttons)
                close_message = message
                break
        
        if close_message:
            # Simulate button click
            view = CloseTicketView(0)  # Owner ID not needed for this
            await view.close_ticket(ctx, None)
        else:
            await ctx.send("Close button not found in this ticket.")
    else:
        await ctx.send("This is not a ticket channel.")

# Bad word management commands
@bot.command()
@commands.has_permissions(manage_messages=True)
async def add_bad_word(ctx, language: str, *, word: str):
    """Add a bad word to the filter"""
    language = language.lower()
    if language not in ["english", "hinglish"]:
        await ctx.send("Language must be 'english' or 'hinglish'")
        return
    
    filename = f"bad_words_{language}.txt"
    word = word.lower()
    
    # Check if word already exists
    if language == "english":
        if word in english_bad_words:
            await ctx.send(f"'{word}' is already in the {language} bad words list.")
            return
        english_bad_words.append(word)
    else:
        if word in hinglish_bad_words:
            await ctx.send(f"'{word}' is already in the {language} bad words list.")
            return
        hinglish_bad_words.append(word)
    
    # Add to file
    with open(filename, "a") as f:
        f.write(f"{word}\n")
    
    await ctx.send(f"Added '{word}' to {language} bad words list.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def remove_bad_word(ctx, language: str, *, word: str):
    """Remove a bad word from the filter"""
    language = language.lower()
    if language not in ["english", "hinglish"]:
        await ctx.send("Language must be 'english' or 'hinglish'")
        return
    
    filename = f"bad_words_{language}.txt"
    word = word.lower()
    
    # Remove from list
    if language == "english":
        if word not in english_bad_words:
            await ctx.send(f"'{word}' is not in the {language} bad words list.")
            return
        english_bad_words.remove(word)
    else:
        if word not in hinglish_bad_words:
            await ctx.send(f"'{word}' is not in the {language} bad words list.")
            return
        hinglish_bad_words.remove(word)
    
    # Update file
    with open(filename, "w") as f:
        if language == "english":
            f.write("\n".join(english_bad_words))
        else:
            f.write("\n".join(hinglish_bad_words))
    
    await ctx.send(f"Removed '{word}' from {language} bad words list.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def list_bad_words(ctx, language: str = None):
    """List all bad words in the filter"""
    if language and language.lower() not in ["english", "hinglish"]:
        await ctx.send("Language must be 'english' or 'hinglish'")
        return
    
    response = ""
    
    if not language or language.lower() == "english":
        if not english_bad_words:
            response += "No English bad words configured.\n"
        else:
            response += f"**English bad words ({len(english_bad_words)}):**\n{', '.join(english_bad_words)}\n\n"
    
    if not language or language.lower() == "hinglish":
        if not hinglish_bad_words:
            response += "No Hinglish bad words configured."
        else:
            response += f"**Hinglish bad words ({len(hinglish_bad_words)}):**\n{', '.join(hinglish_bad_words)}"
    
    # Split if too long
    if len(response) > 2000:
        chunks = [response[i:i+2000] for i in range(0, len(response), 2000)]
        for chunk in chunks:
            await ctx.send(chunk)
    else:
        await ctx.send(response)

# Run the bot
if __name__ == "__main__":
    # Get token from environment variable (for Railway)
    token = os.environ.get('MTQxOTE4NDc0NDYxNjQzMTcxNw.GAUzEd.kqL3An09-6R-EK81uWiXKVlr_MibgVQcG5jaZ4')
    if not token:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        exit(1)
    
    bot.run(token)
