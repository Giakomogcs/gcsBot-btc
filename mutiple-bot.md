# Managing Multiple Bot Instances

Jules Bot is designed to support multiple, isolated bot instances. Each bot you create will have its own configuration, database schema, and log files, allowing you to run different strategies or manage separate accounts simultaneously.

The command-line interface (`run.py`) has been streamlined to make managing these bots simple and intuitive.

## The New Bot Management Workflow

The entire lifecycle of a bot—from creation to deletion—is handled through interactive commands.

### 1. Create a New Bot

To create a new bot, use the `new-bot` command:
```bash
python run.py new-bot
```
The script will ask you for a name for your new bot and automatically create the necessary `.env.<bot_name>` configuration file from the template.

### 2. Run, Test, or Display a Bot

When you want to run a bot, simply use the `trade`, `test`, or `display` command without any arguments:
```bash
# To run a bot in test mode
python run.py test

# To run a bot in live mode
python run.py trade

# To view the TUI dashboard for a bot
python run.py display
```
If you have multiple bots, the script will present you with an interactive menu to choose which bot you want to use for that command.

### 3. Delete a Bot

To remove a bot you no longer need, use the `delete-bot` command:
```bash
python run.py delete-bot
```
You will be presented with a list of bots to choose from. For safety, the script will ask for a final confirmation before deleting the bot's configuration file.

---

## Comprehensive Documentation

For a complete guide to all features, commands, and the system architecture, please refer to the main [**README.md**](README.md) file.
