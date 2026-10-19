import discord
from discord.ext import commands
import os
import json
import asyncio
import traceback
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
XAI_API_KEY = os.getenv("XAI_API_KEY")
OWNER_IDS = [int(i.strip()) for i in os.getenv("OWNER_IDS", "").split(",") if i.strip()]
MODEL = os.getenv("GROK_MODEL", "grok-4")
PREFIX = ":"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

ai_client = AsyncOpenAI(
    api_key=XAI_API_KEY,
    base_url="https://api.x.ai/v1",
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Send a message in the current channel or another channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "channel_id": {"type": "string"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reply_to_message",
            "description": "Reply to the user's command message.",
            "parameters": {
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_recent_messages",
            "description": "Delete recent messages in the current channel.",
            "parameters": {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_text_channel",
            "description": "Create a text channel in the current server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "topic": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kick_member",
            "description": "Kick a member by user id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_code",
            "description": (
                "Run async Python against the live Discord bot when no other tool fits. "
                "Use this for channel permissions, hiding channels, roles, timeouts, bans, "
                "nicknames, slowmode, or anything else discord.py can do. "
                "The code is the body of an async function. Use await. "
                "Names already in scope: message, channel, guild, author, bot, discord, asyncio. "
                "Return a short status string. Never claim a capability is missing if this tool exists."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python statements forming the body of an async function. Must use await for Discord calls.",
                    }
                },
                "required": ["code"],
            },
        },
    },
]

SYSTEM_PROMPT = """You control a Discord bot. The user message is an order. Do it.

Rules:
- Prefer the named tools when they fit.
- If they do not fit, call run_code. Do not tell the user you lack a tool.
- run_code is the body of an async function. Use await. Return a short status string.
- Names in scope: message, channel, guild, author, bot, discord, asyncio.
- channel.id is the current channel. guild.default_role is @everyone.
- To hide a channel from @everyone:
    target = bot.get_channel(CHANNEL_ID) or channel
    await target.set_permissions(guild.default_role, view_channel=False)
    return "Hid the channel from @everyone"
- To show it again: await target.set_permissions(guild.default_role, view_channel=True)
- If a tool result is an error, call run_code again with a fix. Do not give up after one failure.
- After the action succeeds, reply with one short confirmation. Do not dump the code.
"""


def _assistant_message(response_message):
    payload = {
        "role": "assistant",
        "content": response_message.content or "",
    }
    if response_message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in response_message.tool_calls
        ]
    return payload


async def run_user_code(code: str, message: discord.Message) -> str:
    indented = "\n".join("    " + line if line.strip() else "" for line in code.splitlines())
    if not indented.strip():
        return "Code error: empty code"
    source = "async def __user_action():\n" + indented + "\n"
    namespace = {
        "discord": discord,
        "bot": bot,
        "message": message,
        "channel": message.channel,
        "guild": message.guild,
        "author": message.author,
        "asyncio": asyncio,
    }
    try:
        exec(source, namespace, namespace)
        result = await asyncio.wait_for(namespace["__user_action"](), timeout=25)
        return str(result) if result is not None else "Code ran successfully."
    except Exception:
        return "Code error:\n" + traceback.format_exc(limit=6)


async def execute_tool(tool_name: str, arguments: dict, message: discord.Message) -> str:
    try:
        if tool_name == "send_message":
            content = arguments.get("content") or ""
            channel = message.channel
            channel_id = arguments.get("channel_id")
            if channel_id:
                channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
            if not channel:
                return "Failed to find channel."
            await channel.send(content)
            return f"Sent message in #{getattr(channel, 'name', channel.id)}."

        if tool_name == "reply_to_message":
            await message.reply(arguments.get("content") or "")
            return "Replied."

        if tool_name == "delete_recent_messages":
            count = min(max(int(arguments.get("count", 1)), 1), 100)
            deleted = await message.channel.purge(limit=count)
            return f"Deleted {len(deleted)} messages."

        if tool_name == "create_text_channel":
            if not message.guild:
                return "Not in a server."
            created = await message.guild.create_text_channel(
                arguments["name"], topic=arguments.get("topic")
            )
            return f"Created #{created.name} ({created.id})."

        if tool_name == "kick_member":
            if not message.guild:
                return "Not in a server."
            member = message.guild.get_member(int(arguments["user_id"]))
            if member is None:
                member = await message.guild.fetch_member(int(arguments["user_id"]))
            await member.kick(reason=arguments.get("reason") or "No reason provided")
            return f"Kicked {member}."

        if tool_name == "run_code":
            return await run_user_code(arguments.get("code") or "", message)

        return f"Unknown tool: {tool_name}"
    except Exception:
        return f"Error executing {tool_name}:\n" + traceback.format_exc(limit=4)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="for :commands")
    )


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.author.bot:
        return
    if not message.content.startswith(PREFIX):
        return
    if OWNER_IDS and message.author.id not in OWNER_IDS:
        await message.reply("You are not authorized to control this bot.")
        return

    instruction = message.content[len(PREFIX):].strip()
    if not instruction:
        await message.reply("Tell me what to do after the colon.")
        return

    async with message.channel.typing():
        try:
            history = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Instruction: {instruction}\n"
                        f"channel_id: {message.channel.id}\n"
                        f"channel_name: {getattr(message.channel, 'name', 'DM')}\n"
                        f"guild_id: {message.guild.id if message.guild else 'none'}\n"
                        f"guild_name: {message.guild.name if message.guild else 'DM'}\n"
                        f"author_id: {message.author.id}"
                    ),
                },
            ]

            final_text = "Done."
            for _ in range(4):
                response = await ai_client.chat.completions.create(
                    model=MODEL,
                    messages=history,
                    tools=TOOLS,
                    tool_choice="auto",
                    max_tokens=1200,
                    temperature=0.2,
                )
                response_message = response.choices[0].message
                if not response_message.tool_calls:
                    final_text = response_message.content or "Done."
                    break

                history.append(_assistant_message(response_message))
                for tool_call in response_message.tool_calls:
                    args = json.loads(tool_call.function.arguments or "{}")
                    result = await execute_tool(tool_call.function.name, args, message)
                    history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result[:3500],
                        }
                    )
            else:
                final_text = "Stopped after several attempts. Check the bot logs."

            if len(final_text) > 1900:
                final_text = final_text[:1900] + "…"
            await message.reply(final_text)
        except Exception as e:
            await message.reply(f"Error: {e}")


if __name__ == "__main__":
    if not DISCORD_TOKEN or not XAI_API_KEY:
        print("Missing DISCORD_TOKEN or XAI_API_KEY")
    else:
        bot.run(DISCORD_TOKEN)
