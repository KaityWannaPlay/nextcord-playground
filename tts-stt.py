import nextcord
from nextcord.ext import commands
import aiohttp
import os
import asyncio
import json
import random
import time
from gtts import gTTS
from nextcord import FFmpegPCMAudio, Embed, Color
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger("ChatBot")

class ChatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.groq_api_key = os.getenv("GROQ_API_KEY", "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")
        self.chat_api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.stt_api_url = "https://api.groq.com/openai/v1/audio/transcriptions"
        
        # Available models - can be changed with commands
        self.available_models = {
            "llama": "llama-3.3-70b-versatile",
            "gemma": "gemma-7b-it",
            "mixtral": "mixtral-8x7b-32768",
            "claude": "claude-3-opus-20240229"
        }
        
        self.chat_model = self.available_models["llama"]
        self.stt_model = "whisper-large-v3"
        self.temperature = 0.7
        self.voice_clients = {}
        self.conversation_history = {}  # Store conversation history per channel
        self.speaking_speed = 1.0  # Normal speed by default
        self.typing_indicators = {}  # Track typing indicators
        self.user_preferences = self.load_preferences()
        self.last_activity = {}  # Track last activity time per channel
        self.idle_messages = [
            "I'm still here if you want to chat!",
            "Been quiet for a bit. How are you doing?",
            "Just checking in. Need any help with anything?",
            "I'm here whenever you're ready to talk again.",
            "Anything on your mind? I'm all ears!",
            "Feel like chatting about something interesting?"
        ]
        
        # Start background tasks
        self.check_idle_channels_task = self.bot.loop.create_task(self.check_idle_channels())
        
        # Personality traits that make the bot feel more human
        self.personality = {
            "greeting_phrases": [
                "Hey there! How's it going?",
                "Hi! Nice to hear from you!",
                "Hello! What's on your mind today?",
                "Hey, great to see you again!"
            ],
            "thinking_phrases": [
                "Hmm, let me think about that...",
                "That's an interesting question...",
                "Let me ponder that for a moment...",
                "Give me a second to think..."
            ],
            "farewell_phrases": [
                "Talk to you later!",
                "Catch you next time!",
                "Until next time!",
                "Looking forward to our next chat!"
            ]
        }
        
    def load_preferences(self):
        try:
            with open('user_preferences.json', 'r') as file:
                return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
            
    def save_preferences(self):
        with open('user_preferences.json', 'w') as file:
            json.dump(self.user_preferences, file)
    
    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"ChatBot is ready and logged in as {self.bot.user}")
        await self.bot.change_presence(activity=nextcord.Activity(
            type=nextcord.ActivityType.listening, 
            name="your voice | !help"
        ))
    
    @commands.command(name="join")
    async def join_voice(self, ctx):
        if ctx.author.voice and ctx.author.voice.channel:
            channel = ctx.author.voice.channel
            if ctx.guild.id not in self.voice_clients:
                vc = await channel.connect()
                self.voice_clients[ctx.guild.id] = vc
                
                embed = Embed(
                    title="🔊 Voice Connected",
                    description=f"Joined {channel.name}! Now listening for voice messages.",
                    color=Color.green()
                )
                embed.set_footer(text="Send audio files or mention me to chat!")
                await ctx.send(embed=embed)
                
                # Greet the user
                greeting = random.choice(self.personality["greeting_phrases"])
                await self.play_voice_message(ctx.guild.id, greeting)
                await ctx.send(greeting)
            else:
                await ctx.send("🔊 **Already in a voice channel!** Use `!move` to change channels.")
        else:
            await ctx.send("❌ You need to be in a voice channel first!")

    @commands.command(name="leave")
    async def leave_voice(self, ctx):
        if ctx.guild.id in self.voice_clients:
            vc = self.voice_clients.pop(ctx.guild.id)
            
            # Say goodbye before disconnecting
            farewell = random.choice(self.personality["farewell_phrases"])
            await ctx.send(farewell)
            await self.play_voice_message(ctx.guild.id, farewell)
            
            # Wait for voice to finish before disconnecting
            while vc.is_playing():
                await asyncio.sleep(0.5)
                
            await vc.disconnect()
            
            embed = Embed(
                title="👋 Voice Disconnected",
                description="I've left the voice channel. Thanks for chatting!",
                color=Color.red()
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ I'm not in a voice channel!")

    @commands.command(name="model")
    async def change_model(self, ctx, model_name=None):
        if model_name is None:
            models_list = "\n".join([f"• **{name}**: {model}" for name, model in self.available_models.items()])
            embed = Embed(
                title="🤖 Available AI Models",
                description=f"Current model: **{self.chat_model}**\n\n{models_list}\n\nUse `!model [name]` to switch.",
                color=Color.blue()
            )
            await ctx.send(embed=embed)
            return
            
        if model_name.lower() in self.available_models:
            self.chat_model = self.available_models[model_name.lower()]
            await ctx.send(f"🔄 Model changed to **{self.chat_model}**")
        else:
            await ctx.send(f"❌ Model not found. Available models: {', '.join(self.available_models.keys())}")

    @commands.command(name="temp")
    async def change_temperature(self, ctx, temp=None):
        if temp is None:
            await ctx.send(f"🌡️ Current temperature: **{self.temperature}**\nUse `!temp [0.1-1.5]` to change.")
            return
            
        try:
            temp = float(temp)
            if 0.1 <= temp <= 1.5:
                self.temperature = temp
                await ctx.send(f"🌡️ Temperature set to **{self.temperature}**")
                
                # Save user preference
                if str(ctx.author.id) not in self.user_preferences:
                    self.user_preferences[str(ctx.author.id)] = {}
                self.user_preferences[str(ctx.author.id)]["temperature"] = temp
                self.save_preferences()
            else:
                await ctx.send("❌ Temperature must be between 0.1 and 1.5")
        except ValueError:
            await ctx.send("❌ Please provide a valid number")

    @commands.command(name="speed")
    async def change_speaking_speed(self, ctx, speed=None):
        if speed is None:
            await ctx.send(f"🔊 Current speaking speed: **{self.speaking_speed}x**\nUse `!speed [0.5-2.0]` to change.")
            return
            
        try:
            speed = float(speed)
            if 0.5 <= speed <= 2.0:
                self.speaking_speed = speed
                await ctx.send(f"🔊 Speaking speed set to **{self.speaking_speed}x**")
                
                # Save user preference
                if str(ctx.author.id) not in self.user_preferences:
                    self.user_preferences[str(ctx.author.id)] = {}
                self.user_preferences[str(ctx.author.id)]["speaking_speed"] = speed
                self.save_preferences()
            else:
                await ctx.send("❌ Speed must be between 0.5 and 2.0")
        except ValueError:
            await ctx.send("❌ Please provide a valid number")

    @commands.command(name="clear")
    async def clear_history(self, ctx):
        channel_id = str(ctx.channel.id)
        if channel_id in self.conversation_history:
            self.conversation_history[channel_id] = []
            await ctx.send("🧹 Conversation history cleared! Let's start fresh.")
        else:
            await ctx.send("📝 No conversation history to clear.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        channel_id = str(message.channel.id)
        self.last_activity[channel_id] = time.time()
        
        # Initialize conversation history for this channel if it doesn't exist
        if channel_id not in self.conversation_history:
            self.conversation_history[channel_id] = []

        # Process audio attachments
        if message.attachments:
            for attachment in message.attachments:
                if attachment.filename.endswith((".mp3", ".wav", ".m4a", ".ogg")):
                    # Show typing indicator
                    async with message.channel.typing():
                        await message.add_reaction("🎧")  # Listening reaction
                        transcription = await self.transcribe_audio(attachment)
                        
                        if transcription:
                            await message.add_reaction("✅")  # Success reaction
                            await message.channel.send(f"🎤 **{message.author.display_name} said:** {transcription}")
                            await self.chat_response(message, transcription)
                        else:
                            await message.add_reaction("❌")  # Failed reaction
                            await message.channel.send("❌ Sorry, I couldn't transcribe that audio file.")

        # Process direct mentions or messages in DMs
        is_mentioned = self.bot.user.mentioned_in(message) and not message.mention_everyone
        is_dm = isinstance(message.channel, nextcord.DMChannel)
        
        if is_mentioned or is_dm:
            # Remove the bot's mention from the message
            content = message.content.replace(f'<@!{self.bot.user.id}>', '').replace(f'<@{self.bot.user.id}>', '').strip()
            
            if not content and is_mentioned:
                # Just a mention with no content, send a greeting
                greeting = random.choice(self.personality["greeting_phrases"])
                await message.channel.send(greeting)
                return
                
            # Process the actual message
            await self.chat_response(message, content)

    async def chat_response(self, message, user_input):
        channel_id = str(message.channel.id)
        
        # Add user message to history
        self.conversation_history[channel_id].append({"role": "user", "content": user_input})
        
        # Keep history to reasonable size
        if len(self.conversation_history[channel_id]) > 20:
            self.conversation_history[channel_id] = self.conversation_history[channel_id][-20:]
        
        # Start typing indicator
        typing_task = asyncio.create_task(self.show_typing_indicator(message.channel))
        self.typing_indicators[channel_id] = typing_task
        
        # Select a "thinking" phrase for more human-like interaction
        thinking_phrase = random.choice(self.personality["thinking_phrases"])
        thinking_msg = await message.channel.send(thinking_phrase)
        
        # Small delay to simulate thinking
        await asyncio.sleep(min(len(user_input) / 50, 2))
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.groq_api_key}"
                }
                
                # System message to make responses more conversational
                system_message = {
                    "role": "system", 
                    "content": (
                        "You are a friendly and conversational AI chatbot in a Discord server. "
                        "You're talking with a real person who might be feeling lonely. "
                        "Be warm, empathetic, and engage naturally like a friend would. "
                        "Ask follow-up questions to show interest. "
                        "Keep responses concise (1-3 paragraphs at most) but meaningful. "
                        "Feel free to use emojis occasionally to express emotion. "
                        "Remember details about the user from previous messages in the conversation."
                    )
                }
                
                # Prepare payload with conversation history
                payload = {
                    "messages": [system_message] + self.conversation_history[channel_id],
                    "model": self.chat_model,
                    "temperature": self.temperature,
                    "max_tokens": 2000,
                    "top_p": 1
                }
                
                async with session.post(self.chat_api_url, headers=headers, json=payload) as response:
                    # Delete the thinking message
                    await thinking_msg.delete()
                    
                    if response.status == 200:
                        data = await response.json()
                        reply = data.get('choices', [])[0].get('message', {}).get('content', 'I have no response.')
                        
                        # Add bot response to history
                        self.conversation_history[channel_id].append({"role": "assistant", "content": reply})
                        
                        # Split long responses into chunks
                        if len(reply) > 2000:
                            chunks = [reply[i:i+1994] for i in range(0, len(reply), 1994)]
                            for i, chunk in enumerate(chunks):
                                if i == 0:
                                    await message.channel.send(chunk)
                                else:
                                    await message.channel.send(f"...(continued) {chunk}")
                        else:
                            await message.channel.send(reply)
                            
                        # Say the response in voice if in a voice channel
                        if message.guild and message.guild.id in self.voice_clients:
                            await self.play_voice_message(message.guild.id, reply[:500])  # Limit voice to 500 chars
                    else:
                        error_data = await response.text()
                        logger.error(f"API Error: {error_data}")
                        await message.channel.send("❌ I'm having trouble connecting to my brain right now. Please try again later.")
        except Exception as e:
            logger.error(f"Error in chat_response: {str(e)}", exc_info=True)
            await message.channel.send("❌ Something went wrong processing your message. Please try again.")
            
        finally:
            # Cancel typing indicator
            if channel_id in self.typing_indicators and not self.typing_indicators[channel_id].done():
                self.typing_indicators[channel_id].cancel()
                
    async def show_typing_indicator(self, channel):
        try:
            async with channel.typing():
                # Keep typing until cancelled
                while True:
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in typing indicator: {str(e)}")

    async def transcribe_audio(self, attachment):
        file_path = f"./temp_{attachment.filename}"
        try:
            await attachment.save(file_path)
            
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {self.groq_api_key}"}
                form_data = aiohttp.FormData()
                form_data.add_field("model", self.stt_model)
                form_data.add_field("response_format", "verbose_json")
                form_data.add_field("file", open(file_path, "rb"), filename=file_path)

                async with session.post(self.stt_api_url, headers=headers, data=form_data) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("text")
                    else:
                        error_data = await response.text()
                        logger.error(f"STT API Error: {error_data}")
                        return None
        except Exception as e:
            logger.error(f"Error in transcribe_audio: {str(e)}", exc_info=True)
            return None
        finally:
            # Clean up the temporary file
            if os.path.exists(file_path):
                os.remove(file_path)

    async def play_voice_message(self, guild_id, text):
        if guild_id in self.voice_clients:
            vc = self.voice_clients[guild_id]
            if vc and vc.is_connected():
                try:
                    # Split text into sentences for more natural pauses
                    sentences = self.split_into_sentences(text)
                    file_path = f"response_{guild_id}.mp3"
                    
                    # Create TTS with appropriate speaking speed
                    tts = gTTS(text=text, slow=(self.speaking_speed < 1.0))
                    tts.save(file_path)
                    
                    # Play the audio
                    if vc.is_playing():
                        vc.stop()
                        
                    vc.play(FFmpegPCMAudio(file_path))
                    
                    # Wait for voice to finish
                    while vc.is_playing():
                        await asyncio.sleep(0.5)
                        
                    # Clean up the file
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        
                except Exception as e:
                    logger.error(f"Error in play_voice_message: {str(e)}", exc_info=True)

    def split_into_sentences(self, text):
        # Simple sentence splitting
        return [s.strip() for s in text.replace('!', '.').replace('?', '.').split('.') if s.strip()]
        
    async def check_idle_channels(self):
        """Background task to check for idle channels and engage users"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                current_time = time.time()
                for channel_id, last_time in list(self.last_activity.items()):
                    # If channel has been idle for between 10-15 minutes (randomly check) but less than 30 minutes
                    idle_time = current_time - last_time
                    if 600 < idle_time < 1800 and random.random() < 0.1:  # 10% chance every check
                        channel = self.bot.get_channel(int(channel_id))
                        if channel:
                            idle_message = random.choice(self.idle_messages)
                            await channel.send(idle_message)
                            # Update last activity
                            self.last_activity[channel_id] = current_time
            except Exception as e:
                logger.error(f"Error in check_idle_channels: {str(e)}", exc_info=True)
                
            # Check every 5 minutes
            await asyncio.sleep(300)

    @commands.command(name="help")
    async def help_command(self, ctx):
        embed = Embed(
            title="🤖 ChatBot Help",
            description="I'm your friendly AI chat companion! Here's how to interact with me:",
            color=Color.blue()
        )
        
        embed.add_field(
            name="📝 Chat Commands",
            value=(
                "`@BotName [message]` - Chat with me by mentioning me\n"
                "`!join` - I'll join your voice channel\n"
                "`!leave` - I'll leave the voice channel\n"
                "`!clear` - Clear our conversation history\n"
            ),
            inline=False
        )
        
        embed.add_field(
            name="⚙️ Settings",
            value=(
                "`!model` - View or change AI model\n"
                "`!temp [0.1-1.5]` - Set AI creativity (higher = more creative)\n"
                "`!speed [0.5-2.0]` - Set voice speaking speed\n"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🎤 Voice Features",
            value=(
                "• Send audio files for me to respond to\n"
                "• I'll speak my responses in voice channels\n"
                "• I understand natural conversations\n"
            ),
            inline=False
        )
        
        embed.set_footer(text="I'm here to chat whenever you're feeling lonely! 💖")
        await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(ChatCog(bot))
