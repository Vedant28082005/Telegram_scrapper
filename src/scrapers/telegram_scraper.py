import asyncio
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from typing import List, Dict, Any, Optional, Callable
import os
from datetime import datetime
import sys

# Add project root to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from src.utils.config import config
from src.utils.logger import logger

class TelegramScraper:
    def __init__(self):
        self.config = config.get_telegram_config()
        self.client = None
        self.session_name = self.config.get('session_name', 'message_scraper')
        self.target_chats = self.config.get('target_chats', [])
        self.message_callback = None
        self.is_running = False
        
    async def initialize(self):
        """Initialize Telegram client"""
        try:
            # Create client
            self.client = TelegramClient(
                f"sessions/{self.session_name}",
                self.config['api_id'],
                self.config['api_hash']
            )
            
            # Create sessions directory if it doesn't exist
            os.makedirs("sessions", exist_ok=True)
            
            logger.info("🔗 Connecting to Telegram...")
            await self.client.start(phone=self.config['phone_number'])
            
            # Get user info
            me = await self.client.get_me()
            logger.info(f"✅ Connected as {me.first_name} ({me.username or 'No username'})")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Telegram client: {e}")
            return False
    
    async def get_chat_info(self, chat_identifier) -> Optional[Dict]:
        """Get information about a chat"""
        try:
            entity = await self.client.get_entity(chat_identifier)
            return {
                'id': entity.id,
                'title': getattr(entity, 'title', getattr(entity, 'first_name', 'Unknown')),
                'type': entity.__class__.__name__,
                'username': getattr(entity, 'username', None)
            }
        except Exception as e:
            logger.error(f"❌ Failed to get chat info for {chat_identifier}: {e}")
            return None
    
    async def validate_target_chats(self) -> List[Dict]:
        """Validate and get info for all target chats"""
        valid_chats = []
        
        for chat in self.target_chats:
            chat_info = await self.get_chat_info(chat)
            if chat_info:
                valid_chats.append(chat_info)
                logger.info(f"✅ Chat validated: {chat_info['title']} (ID: {chat_info['id']})")
            else:
                logger.warning(f"⚠️ Invalid chat: {chat}")
        
        return valid_chats
    
    def set_message_callback(self, callback: Callable):
        """Set callback function for new messages"""
        self.message_callback = callback
    
    async def process_message(self, event):
        """Process incoming message"""
        try:
            message = event.message
            
            # Get chat info
            chat = await event.get_chat()
            sender = await event.get_sender()
            
            # Extract message data
            message_data = {
                'id': message.id,
                'chat_id': chat.id,
                'chat_title': getattr(chat, 'title', getattr(chat, 'first_name', 'Unknown')),
                'sender_id': sender.id if sender else None,
                'sender_name': self._get_sender_name(sender),
                'timestamp': message.date,
                'text': message.text or '',
                'media_type': None,
                'media_path': None,
                'has_media': bool(message.media),
                'source': 'telegram'
            }
            
            # Handle media messages
            if message.media:
                message_data['media_type'] = self._get_media_type(message.media)
                
                # Download media if it's an image
                if isinstance(message.media, (MessageMediaPhoto, MessageMediaDocument)):
                    media_path = await self._download_media(message, chat.id, message.id)
                    message_data['media_path'] = media_path
            
            # Log message receipt
            content_preview = message_data['text'] or f"[{message_data['media_type']}]"
            logger.log_message_received(
                f"Telegram/{message_data['chat_title']}", 
                message_data['sender_name'], 
                content_preview
            )
            
            # Call callback if set
            if self.message_callback:
                await self.message_callback(message_data)
                
        except Exception as e:
            logger.error(f"❌ Error processing Telegram message: {e}")
    
    def _get_sender_name(self, sender) -> str:
        """Get human-readable sender name"""
        if not sender:
            return "Unknown"
        
        if hasattr(sender, 'first_name'):
            name = sender.first_name
            if hasattr(sender, 'last_name') and sender.last_name:
                name += f" {sender.last_name}"
            return name
        elif hasattr(sender, 'title'):
            return sender.title
        elif hasattr(sender, 'username'):
            return f"@{sender.username}"
        else:
            return f"User {sender.id}"
    
    def _get_media_type(self, media) -> str:
        """Determine media type"""
        if isinstance(media, MessageMediaPhoto):
            return "photo"
        elif isinstance(media, MessageMediaDocument):
            if media.document.mime_type.startswith('image/'):
                return "image"
            elif media.document.mime_type.startswith('video/'):
                return "video"
            elif media.document.mime_type.startswith('audio/'):
                return "audio"
            else:
                return "document"
        else:
            return "other"
    
    async def _download_media(self, message, chat_id: int, message_id: int) -> Optional[str]:
        """Download media file"""
        try:
            # Create media directory
            media_dir = f"media/telegram/{chat_id}"
            os.makedirs(media_dir, exist_ok=True)
            
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{message_id}_{timestamp}"
            
            # Download file
            file_path = await self.client.download_media(
                message.media,
                file=f"{media_dir}/{filename}"
            )
            
            logger.debug(f"📥 Downloaded media: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"❌ Failed to download media: {e}")
            return None
    
    async def start_monitoring(self):
        """Start monitoring target chats"""
        if not self.client:
            if not await self.initialize():
                return False
        
        # Validate target chats
        valid_chats = await self.validate_target_chats()
        if not valid_chats:
            logger.error("❌ No valid chats to monitor")
            return False
        
        logger.info(f"👀 Starting to monitor {len(valid_chats)} chats...")
        
        # Register event handler for new messages
        @self.client.on(events.NewMessage(chats=self.target_chats))
        async def message_handler(event):
            await self.process_message(event)
        
        self.is_running = True
        logger.info("✅ Telegram monitoring started")
        
        try:
            # Keep client running
            await self.client.run_until_disconnected()
        except KeyboardInterrupt:
            logger.info("🛑 Received interrupt signal")
        finally:
            self.is_running = False
            await self.stop_monitoring()
    
    async def stop_monitoring(self):
        """Stop monitoring and cleanup"""
        self.is_running = False
        if self.client:
            logger.info("🔌 Disconnecting from Telegram...")
            await self.client.disconnect()
            logger.info("✅ Telegram client disconnected")
    
    async def send_test_message(self, chat_id: int, message: str):
        """Send a test message (for debugging)"""
        try:
            if not self.client:
                await self.initialize()
            
            await self.client.send_message(chat_id, message)
            logger.info(f"✅ Test message sent to {chat_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send test message: {e}")
            return False

# Test function
async def test_telegram_connection():
    """Test Telegram connection and list available chats"""
    scraper = TelegramScraper()
    
    if await scraper.initialize():
        logger.info("🔍 Testing Telegram connection...")
        
        # Get list of dialogs (chats)
        async for dialog in scraper.client.iter_dialogs(limit=10):
            logger.info(f"📱 Available chat: {dialog.name} (ID: {dialog.id})")
        
        await scraper.stop_monitoring()
        return True
    else:
        return False

if __name__ == "__main__":
    # Test the scraper
    asyncio.run(test_telegram_connection())