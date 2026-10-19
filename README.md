# Discord AI Bot Setup

This bot listens for messages starting with `:` and uses the Grok AI (via xAI API) to interpret natural language instructions and perform Discord actions (send messages, delete messages, create channels, kick members, etc.).

## Prerequisites
- Python 3.10+
- Discord Bot Token (from https://discord.com/developers/applications)
  - Enable **Message Content Intent** and **Server Members Intent** in the Bot settings.
  - Invite the bot with permissions: Send Messages, Manage Messages, Manage Channels, Kick Members, Read Message History.
- xAI API Key (from https://console.x.ai)

## Installation
1. Clone or copy these files.
2. `pip install -r requirements.txt`
3. Create a `.env` file:
   ```
   DISCORD_TOKEN=your_discord_bot_token_here
   XAI_API_KEY=your_xai_api_key_here
   OWNER_IDS=123456789012345678,987654321098765432  # Optional: your Discord user ID(s). Leave empty to allow anyone.
   ```
4. Run: `python discord_ai_bot.py`

## Usage
In Discord, type:
- `:say hello to everyone`
- `:delete the last 5 messages`
- `:create a channel called announcements`
- `:kick user 123456789 for being annoying`
- `:what is the weather like?` (will respond conversationally)

The bot uses function calling to decide and execute actions. Destructive actions should be confirmed by the AI.

## Notes
- Model is set to `grok-4`. Change in code if needed (check available models).
- Restrict OWNER_IDS for safety.
- Host it on a VPS, Replit, Railway, or your machine (keep it running).
- Extend TOOLS and `execute_tool` for more actions (ban, timeout, change nickname, etc.).

Enjoy controlling your bot with natural language!
