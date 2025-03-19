import nextcord
from nextcord.ext import commands
from nextcord.ui import View, Button, Select, Modal, TextInput
from typing import Optional, List, Tuple, Dict
import datetime
import inspect
import os

class PageJumpModal(Modal):
    def __init__(self, help_menu):
        super().__init__(title="Jump to Page")
        self.help_menu = help_menu

        self.page_input = TextInput(
            label=f"Enter page (1-{self.help_menu.max_pages})",
            placeholder="Enter page number...",
            min_length=1,
            max_length=5,
            required=True
        )
        self.add_item(self.page_input)

    async def callback(self, interaction: nextcord.Interaction):
        if interaction.user != self.help_menu.ctx.author:
            return await interaction.response.send_message("This menu is not for you!", ephemeral=True)

        try:
            page_num = int(self.page_input.value)
            if 1 <= page_num <= self.help_menu.max_pages:
                self.help_menu.current_page = page_num - 1
                self.help_menu.update_button_states()
                await interaction.response.edit_message(embed=await self.help_menu.update_embed(), view=self.help_menu)
            else:
                await interaction.response.send_message(f"Page number must be between 1 and {self.help_menu.max_pages}", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Please enter a valid number", ephemeral=True)

class HelpMenu(View):
    def __init__(self, ctx, bot, commands_per_page=4):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.bot = bot
        self.commands_per_page = commands_per_page
        self.current_page = 0
        self.current_category = "All"
        self.category_commands: Dict[str, List[Tuple[commands.Command, Optional[bool]]]] = self.organize_commands_by_category()
        self.categories = sorted(list(self.category_commands.keys()))
        self.max_pages_per_category: Dict[str, int] = {}
        for category in self.categories:
            command_list = self.category_commands[category]
            self.max_pages_per_category[category] = (len(command_list) - 1) // self.commands_per_page + 1 if command_list else 1

        self.max_pages = self.max_pages_per_category[self.current_category]
        self.previous.disabled = True
        self.next.disabled = self.max_pages <= 1
        self.jump.disabled = self.max_pages <= 1

        # Create category dropdown with a reasonable limit
        self.add_category_select()

    def add_category_select(self):
        # Limit the number of categories in the dropdown to 25 (Discord limit)
        displayed_categories = self.categories[:25]
        category_options = [nextcord.SelectOption(label=self.format_category_name(cat), value=cat, default=cat == self.current_category) 
                           for cat in displayed_categories]
        
        self.category_select = Select(placeholder="Select Category", options=category_options)
        self.category_select.callback = self.category_select_callback
        self.add_item(self.category_select)

    def format_category_name(self, category_name):
        # Format category name to fit in Discord's 25-character limit for select options
        if len(category_name) > 25:
            return category_name[:22] + "..."
        return category_name

    def organize_commands_by_category(self) -> Dict[str, List[Tuple[commands.Command, Optional[bool]]]]:
        category_commands: Dict[str, List[Tuple[commands.Command, Optional[bool]]]] = {"All": []}
        
        # Debug information
        print(f"Found {len(self.bot.cogs)} cogs")
        for cog_name, cog in self.bot.cogs.items():
            if cog_name == "HelpCog":  # Skip the help cog itself
                continue
                
            # Debug information
            module_path = cog.__module__
            print(f"Processing cog: {cog_name} from module: {module_path}")
            
            # Get category from module path
            category_name = self.get_category_from_module(module_path)
            print(f"  Assigned to category: {category_name}")
            
            if category_name not in category_commands:
                category_commands[category_name] = []
                
            for cmd in cog.get_commands():
                if isinstance(cmd, commands.Group):
                    category_commands[category_name].append((cmd, True))
                    category_commands["All"].append((cmd, True))
                    for subcmd in cmd.commands:
                        category_commands[category_name].append((subcmd, False))
                        category_commands["All"].append((subcmd, False))
                else:
                    category_commands[category_name].append((cmd, None))
                    category_commands["All"].append((cmd, None))
        
        # Print summary of categories
        for category, cmds in category_commands.items():
            print(f"Category {category}: {len(cmds)} commands")
            
        return category_commands
    
    def get_category_from_module(self, module_path: str) -> str:
        """Extract category name from module path using folder structure"""
        parts = module_path.split('.')
        
        # Print debug information
        print(f"  Module path parts: {parts}")
        
        # Case: Direct module in root (e.g., 'my_cog')
        if len(parts) == 1:
            return "General"
            
        # Special case for security folder
        for part in parts:
            if part.lower() == "security":
                return "Security"
        
        # Case: Module in a package (e.g., 'cogs.my_cog')
        if len(parts) == 2 and parts[0] == "cogs":
            return "General"
        
        # Case: Module in a subfolder (e.g., 'cogs.category.my_cog')
        if len(parts) >= 3 and parts[0] == "cogs":
            # Use the first subfolder as the category
            category = parts[1].replace("_", " ").title()
            return category
        
        # Case: Other structure with 'cogs' somewhere in the path
        for i, part in enumerate(parts):
            if part == "cogs" and i + 1 < len(parts):
                return parts[i + 1].replace("_", " ").title()
        
        # Fallback: check if any part resembles a category
        for part in parts:
            # Look for common category names in the path
            if part.lower() in ["admin", "moderation", "utilities", "fun", "misc", 
                              "music", "economy", "leveling", "games", "security"]:
                return part.title()
        
        # Final fallback
        return "General"

    def format_command(self, cmd: commands.Command, is_group: Optional[bool]) -> str:
        if is_group is True:
            return f"📁 `{cmd.name}`"
        elif is_group is False:
            return f"└─ `{cmd.parent.name} {cmd.name}`"
        else:
            return f"📄 `{cmd.name}`"

    async def update_embed(self) -> nextcord.Embed:
        start = self.current_page * self.commands_per_page
        end = start + self.commands_per_page
        current_commands = self.category_commands[self.current_category][start:end]

        embed = nextcord.Embed(
            title=f"{self.current_category} Commands" if self.current_category != "All" else "All Commands",
            description=f"Use `{self.ctx.prefix}help <command>` for detailed help\nUse `{self.ctx.prefix}help <group> <subcommand>` for subcommand help",
            color=nextcord.Color.blurple()
        )

        if not current_commands:
            embed.description = "No commands in this category."

        for cmd, is_group in current_commands:
            name = self.format_command(cmd, is_group)
            value = cmd.help or "No description provided."

            perms = self.get_required_permissions(cmd)
            if perms:
                value += f"\n*Requires: {', '.join(perms)}*"

            if isinstance(cmd, commands.Group):
                value += f"\n*Has {len(cmd.commands)} subcommands*"

            embed.add_field(name=name, value=value, inline=False)

        embed.set_footer(text=f"Page {self.current_page + 1}/{self.max_pages} | Category: {self.current_category}")
        return embed

    def get_required_permissions(self, command: commands.Command) -> List[str]:
        perms: List[str] = []
        for check in command.checks:
            if hasattr(check, "__qualname__"):
                if "has_permissions" in check.__qualname__:
                    if hasattr(check, "__closure__") and check.__closure__:
                        for cell in check.__closure__:
                            if isinstance(cell.cell_contents, dict):
                                for perm_name, value in cell.cell_contents.items():
                                    if value:
                                        perms.append(perm_name.replace('_', ' ').title())
                elif "has_role" in check.__qualname__:
                    if hasattr(check, "__closure__") and check.__closure__:
                        for cell in check.__closure__:
                            if isinstance(cell.cell_contents, (str, int)):
                                perms.append(f"Role: {cell.cell_contents}")
                elif "guild_only" in check.__qualname__:
                    perms.append("Server Only")
                elif "is_owner" in check.__qualname__:
                    perms.append("Bot Owner")
        return perms

    async def category_select_callback(self, interaction: nextcord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("This menu is not for you!", ephemeral=True)

        selected_category = self.category_select.values[0]
        if selected_category in self.category_commands:
            self.current_category = selected_category
            self.current_page = 0
            self.max_pages = self.max_pages_per_category[self.current_category]
            self.update_button_states()
            
            # Update the dropdown options
            for option in self.category_select.options:
                option.default = option.value == self.current_category
                
            await interaction.response.edit_message(embed=await self.update_embed(), view=self)
        else:
            await interaction.response.send_message(f"Category '{selected_category}' not found.", ephemeral=True)

    @nextcord.ui.button(label="◀", style=nextcord.ButtonStyle.blurple)
    async def previous(self, button: Button, interaction: nextcord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("This menu is not for you!", ephemeral=True)

        self.current_page = max(0, self.current_page - 1)
        self.update_button_states()
        await interaction.response.edit_message(embed=await self.update_embed(), view=self)

    @nextcord.ui.button(label="𝗃𝗎𝗆𝗉", style=nextcord.ButtonStyle.gray)
    async def jump(self, button: Button, interaction: nextcord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("This menu is not for you!", ephemeral=True)

        modal = PageJumpModal(self)
        await interaction.response.send_modal(modal)

    @nextcord.ui.button(label="▶", style=nextcord.ButtonStyle.blurple)
    async def next(self, button: Button, interaction: nextcord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("This menu is not for you!", ephemeral=True)

        self.current_page = min(self.max_pages - 1, self.current_page + 1)
        self.update_button_states()
        await interaction.response.edit_message(embed=await self.update_embed(), view=self)

    def update_button_states(self):
        self.previous.disabled = self.current_page == 0
        self.next.disabled = self.current_page >= self.max_pages - 1
        self.jump.disabled = self.max_pages <= 1


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.remove_command('help')
        self.ctx = None  # Initialize ctx to None

    def get_required_permissions(self, command: commands.Command) -> List[str]:
        perms: List[str] = []
        for check in command.checks:
            if hasattr(check, "__qualname__"):
                if "has_permissions" in check.__qualname__:
                    if hasattr(check, "__closure__") and check.__closure__:
                        for cell in check.__closure__:
                            if isinstance(cell.cell_contents, dict):
                                for perm_name, value in cell.cell_contents.items():
                                    if value:
                                        perms.append(perm_name.replace('_', ' ').title())
                elif "has_role" in check.__qualname__:
                    if hasattr(check, "__closure__") and check.__closure__:
                        for cell in check.__closure__:
                            if isinstance(cell.cell_contents, (str, int)):
                                perms.append(f"Role: {cell.cell_contents}")
                elif "guild_only" in check.__qualname__:
                    perms.append("Server Only")
                elif "is_owner" in check.__qualname__:
                    perms.append("Bot Owner")
        return perms

    def get_command_help(self, command: commands.Command) -> nextcord.Embed:
        embed = nextcord.Embed(
            title=f"Help: {command.qualified_name}",
            color=nextcord.Color.blurple()
        )
        embed.add_field(
            name="Description",
            value=command.help or "No description provided.",
            inline=False
        )
        usage = f"{self.ctx.prefix}{command.qualified_name}"
        if command.signature:
            usage += f" {command.signature}"
        embed.add_field(name="Usage", value=f"`{usage}`", inline=False)

        if isinstance(command, commands.Group):
            subcommands = "\n".join(
                f"`{subcmd.name}` - {subcmd.help or 'No description'}"
                for subcmd in command.commands
            )
            if subcommands:
                embed.add_field(name="Subcommands", value=subcommands, inline=False)

        if command.aliases:
            embed.add_field(
                name="Aliases",
                value=", ".join(f"`{alias}`" for alias in command.aliases),
                inline=False
            )

        perms = self.get_required_permissions(command)
        if perms:
            embed.add_field(
                name="Required Permissions",
                value=", ".join(perms),
                inline=False
            )

        embed.set_footer(text="<> = Required | [] = Optional")
        return embed

    @commands.command(name="help")
    async def help_command(self, ctx, command_input: Optional[str] = None, subcommand_input: Optional[str] = None):
        """Shows help for all commands or specific commands/groups"""
        self.ctx = ctx  # Store ctx for use in get_command_help
        
        if not command_input:
            menu = HelpMenu(ctx, self.bot)
            return await ctx.send(embed=await menu.update_embed(), view=menu)

        if subcommand_input:
            group_cmd = self.bot.get_command(command_input)
            if not group_cmd or not isinstance(group_cmd, commands.Group):
                return await ctx.send(f"❌ Command group `{command_input}` not found.")

            cmd = group_cmd.get_command(subcommand_input)
            if not cmd:
                return await ctx.send(f"❌ Subcommand `{subcommand_input}` not found in `{command_input}`.")
        else:
            cmd = self.bot.get_command(command_input)
            if not cmd:
                return await ctx.send(f"❌ Command `{command_input}` not found.")

        await ctx.send(embed=self.get_command_help(cmd))

    @help_command.error
    async def help_command_error(self, ctx, error):
        if isinstance(error, commands.CommandError):
            await ctx.send(f"❌ An error occurred: {str(error)}")

def setup(bot):
    bot.add_cog(HelpCog(bot))
      
