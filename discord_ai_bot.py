import discord
from discord.ext import commands
import os
import json
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# Configuration
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
XAI_API_KEY = os.getenv("XAI_API_KEY")
OWNER_IDS = [int(id.strip()) for id in os.getenv("OWNER_IDS", "").split(",") if id.strip()]  # Comma-separated Discord user IDs
PREFIX = ":"

# Initialize clients
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # For member actions if needed
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

ai_client = AsyncOpenAI(
    api_key=XAI_API_KEY,
    base_url="https://api.x.ai/v1"
)

# Define tools the AI can call
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Send a message to the current channel or a specified channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The message content to send"},
                    "channel_id": {"type": "string", "description": "Optional channel ID to send to (defaults to current)"}
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reply_to_message",
            "description": "Reply to the user's message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The reply content"}
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_recent_messages",
            "description": "Delete a number of recent messages in the channel (requires Manage Messages permission).",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of messages to delete (1-100)"}
                },
                "required": ["count"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_text_channel",
            "description": "Create a new text channel in the server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the channel"},
                    "topic": {"type": "string", "description": "Optional topic/description"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kick_member",
            "description": "Kick a member from the server (requires Kick Members permission). Use user ID or mention.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Discord user ID of the member to kick"},
                    "reason": {"type": "string", "description": "Reason for the kick"}
                },
                "required": ["user_id"]
            }
        }
    }
]

SYSTEM_PROMPT = """You are an AI-powered Discord bot. The user gives you natural language instructions starting with ':'.
Interpret the instruction and either respond conversationally or use the available tools to perform Discord actions.
Be helpful, concise, and execute what the user asks when possible.
Only use tools when an action is needed. Always confirm actions if destructive.
Current context: you are responding in a Discord server/channel."""

async def execute_tool(tool_name: str, arguments: dict, message: discord.Message):
    """Execute the tool called by the AI and return the result as a string."""
    try:
        if tool_name == "send_message":
            content = arguments.get("content")
            channel_id = arguments.get("channel_id")
            channel = message.channel
            if channel_id:
                channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
            if channel:
                await channel.send(content)
                return f"Sent message: {content}"
            return "Failed to find channel."

        elif tool_name == "reply_to_message":
            content = arguments.get("content")
            await message.reply(content)
            return f"Replied: {content}"

        elif tool_name == "delete_recent_messages":
            count = min(max(arguments.get("count", 1), 1), 100)
            deleted = await message.channel.purge(limit=count)
            return f"Deleted {len(deleted)} messages."

        elif tool_name == "create_text_channel":
            name = arguments.get("name")
            topic = arguments.get("topic")
            if message.guild:
                channel = await message.guild.create_text_channel(name, topic=topic)
                return f"Created channel #{channel.name}"
            return "Not in a guild."

        elif tool_name == "kick_member":
            user_id = arguments.get("user_id")
            reason = arguments.get("reason", "No reason provided")
            if message.guild:
                member = message.guild.get_member(int(user_id))
                if member:
                    await member.kick(reason=reason)
                    return f"Kicked {member.display_name}."
                return "Member not found."
            return "Not in a guild."

        else:
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        return f"Error executing {tool_name}: {str(e)}"

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="for :commands"))

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.author.bot:
        return

    # Only respond to prefix and authorized owners (or empty list = anyone)
    if not message.content.startswith(PREFIX):
        return
    if OWNER_IDS and message.author.id not in OWNER_IDS:
        await message.reply("You are not authorized to control this bot.")
        return

    instruction = message.content[len(PREFIX):].strip()
    if not instruction:
        await message.reply("Tell me what to do after the colon!")
        return

    async with message.channel.typing():
        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Instruction: {instruction}\nContext: Channel '{message.channel.name}' in guild '{message.guild.name if message.guild else 'DM'}'."}
            ]

            response = await ai_client.chat.completions.create(
                model="grok-4",  # or "grok-3" / "grok-beta" depending on availability
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=1000,
                temperature=0.7
            )

            response_message = response.choices[0].message

            # Handle tool calls
            if response_message.tool_calls:
                # Append the assistant's tool call message
                messages.append(response_message)

                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    result = await execute_tool(function_name, function_args, message)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })

                # Get final response after tools
                final_response = await ai_client.chat.completions.create(
                    model="grok-4",
                    messages=messages,
                    max_tokens=500
                )
                final_content = final_response.choices[0].message.content or "Done."
                await message.reply(final_content)
            else:
                # Direct text response
                content = response_message.content or "I understood but have nothing to say."
                await message.reply(content)

        except Exception as e:
            await message.reply(f"Error: {str(e)}")

# Run the bot
if __name__ == "__main__":
    if not DISCORD_TOKEN or not XAI_API_KEY:
        print("Missing DISCORD_TOKEN or XAI_API_KEY in .env")
    else:
        bot.run(DISCORD_TOKEN)
