import asyncio
import aiohttp
import json
from typing import Dict, Any, List, Optional
import time
from datetime import datetime
import sys
import os

# Add project root to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from src.utils.config import config
from src.utils.logger import logger

class FCMNotifier:
    def __init__(self):
        self.notification_config = config.get_notification_config()
        self.fcm_config = self.notification_config.get('fcm', {})
        self.server_key = self.fcm_config.get('server_key')
        self.device_token = self.fcm_config.get('device_token')
        
        # FCM endpoint
        self.fcm_url = "https://fcm.googleapis.com/fcm/send"
        
        # Notification settings
        self.duration = self.notification_config.get('duration', 30)
        self.priority = self.notification_config.get('priority', 'high')
        self.sound_enabled = self.notification_config.get('sound', True)
        self.vibration_enabled = self.notification_config.get('vibration', True)
        
        # Test mode
        self.test_mode = config.is_test_mode()
        
        logger.info("📱 FCM Notifier initialized")
    
    def _create_notification_payload(self, formatted_message: str, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create FCM notification payload"""
        
        # Extract title and body from formatted message
        lines = formatted_message.strip().split('\n')
        title = lines[0] if lines else "New Message"
        
        # Clean title (remove emojis for title, keep for body)
        clean_title = title.replace('🔔', '').replace('**', '').strip()
        
        # Create notification payload
        payload = {
            "to": self.device_token,
            "priority": self.priority,
            "notification": {
                "title": clean_title[:50],  # Limit title length
                "body": formatted_message[:300],  # Limit body length
                "sound": "default" if self.sound_enabled else None,
                "badge": 1,
                "tag": f"message_{message_data.get('id', int(time.time()))}",
                "icon": "ic_notification",
                "color": "#FF5722",  # Orange color for attention
                "click_action": "FLUTTER_NOTIFICATION_CLICK"
            },
            "data": {
                "message_id": str(message_data.get('id', '')),
                "source": message_data.get('source', ''),
                "chat_id": str(message_data.get('chat_id', '')),
                "chat_title": message_data.get('chat_title', ''),
                "sender_name": message_data.get('sender_name', ''),
                "timestamp": message_data.get('timestamp', datetime.now()).isoformat(),
                "has_media": str(message_data.get('has_media', False)),
                "media_type": message_data.get('media_type', ''),
                "duration": str(self.duration),
                "type": "message_alert"
            },
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": "message_alerts",
                    "sound": "default" if self.sound_enabled else None,
                    "vibrate_timings": ["0s", "0.5s", "0.5s", "0.5s"] if self.vibration_enabled else None,
                    "priority": "high",
                    "visibility": "public",
                    "ongoing": True,  # Makes notification persistent
                    "auto_cancel": False,  # Prevents easy dismissal
                    "sticky": True,
                    "local_only": False,
                    "default_sound": True,
                    "default_vibrate": True,
                    "default_light_settings": True
                }
            }
        }
        
        return payload
    
    async def send_notification(self, formatted_message: str, message_data: Dict[str, Any]) -> bool:
        """Send notification via FCM"""
        if not self.server_key or not self.device_token:
            logger.error("❌ FCM server key or device token not configured")
            return False
        
        if self.test_mode:
            logger.info(f"🧪 TEST MODE: Would send notification:\n{formatted_message}")
            return True
        
        try:
            # Create payload
            payload = self._create_notification_payload(formatted_message, message_data)
            
            # Headers
            headers = {
                "Authorization": f"key={self.server_key}",
                "Content-Type": "application/json"
            }
            
            # Send notification
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.fcm_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    
                    response_text = await response.text()
                    
                    if response.status == 200:
                        response_data = json.loads(response_text)
                        
                        if response_data.get('success', 0) > 0:
                            logger.log_notification_sent("FCM", True)
                            
                            # Send follow-up notifications for persistence (30-second duration)
                            if self.duration > 5:
                                asyncio.create_task(self._send_persistent_notifications(
                                    formatted_message, message_data
                                ))
                            
                            return True
                        else:
                            error = response_data.get('results', [{}])[0].get('error', 'Unknown error')
                            logger.error(f"❌ FCM send failed: {error}")
                            return False
                    else:
                        logger.error(f"❌ FCM HTTP error {response.status}: {response_text}")
                        return False
        
        except asyncio.TimeoutError:
            logger.error("❌ FCM notification timeout")
            return False
        except Exception as e:
            logger.error(f"❌ FCM notification error: {e}")
            return False
    
    async def _send_persistent_notifications(self, formatted_message: str, message_data: Dict[str, Any]):
        """Send follow-up notifications to maintain 30-second duration"""
        try:
            # Calculate number of follow-ups needed
            follow_ups = min(self.duration // 5, 6)  # Max 6 follow-ups
            
            for i in range(follow_ups):
                await asyncio.sleep(5)  # Wait 5 seconds between notifications
                
                # Create follow-up payload with slight variation
                follow_up_message = f"🔴 URGENT: {formatted_message}"
                follow_up_data = message_data.copy()
                follow_up_data['id'] = f"{message_data.get('id', 'unknown')}_followup_{i+1}"
                
                # Send follow-up
                payload = self._create_notification_payload(follow_up_message, follow_up_data)
                payload['notification']['tag'] = f"urgent_message_{int(time.time())}_{i}"
                
                headers = {
                    "Authorization": f"key={self.server_key}",
                    "Content-Type": "application/json"
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.fcm_url, json=payload, headers=headers) as response:
                        if response.status == 200:
                            logger.debug(f"📱 Follow-up notification {i+1} sent")
                        else:
                            logger.warning(f"⚠️ Follow-up notification {i+1} failed")
                            
        except Exception as e:
            logger.error(f"❌ Error sending persistent notifications: {e}")
    
    async def send_test_notification(self) -> bool:
        """Send a test notification"""
        test_message = """🔔 **Test Notification**
        
📱 **Source**: Message Scraper Test
👤 **From**: System
🕐 **Time**: Now

📝 **Content**:
This is a test notification to verify FCM is working correctly.

---
✅ FCM Test Successful"""
        
        test_data = {
            'id': 'test_' + str(int(time.time())),
            'source': 'test',
            'chat_id': 'test_chat',
            'chat_title': 'Test Chat',
            'sender_name': 'Test System',
            'timestamp': datetime.now(),
            'has_media': False,
            'media_type': None
        }
        
        logger.info("🧪 Sending FCM test notification...")
        result = await self.send_notification(test_message, test_data)
        
        if result:
            logger.info("✅ FCM test notification sent successfully")
        else:
            logger.error("❌ FCM test notification failed")
        
        return result
    
    async def send_urgent_alert(self, title: str, message: str) -> bool:
        """Send urgent system alert"""
        urgent_message = f"""🚨 **URGENT ALERT**
        
⚠️ **{title}**

{message}

---
🔴 System Alert - {datetime.now().strftime('%H:%M:%S')}"""
        
        alert_data = {
            'id': 'alert_' + str(int(time.time())),
            'source': 'system',
            'chat_id': 'system_alert',
            'chat_title': 'System Alerts',
            'sender_name': 'Message Scraper',
            'timestamp': datetime.now(),
            'has_media': False,
            'media_type': None
        }
        
        return await self.send_notification(urgent_message, alert_data)
    
    def validate_config(self) -> List[str]:
        """Validate FCM configuration"""
        errors = []
        
        if not self.server_key:
            errors.append("FCM server key is required")
        
        if not self.device_token:
            errors.append("FCM device token is required")
        
        if self.server_key and not self.server_key.startswith('AAAA'):
            errors.append("FCM server key format appears invalid")
        
        if self.device_token and len(self.device_token) < 50:
            errors.append("FCM device token appears too short")
        
        return errors
    
    async def get_device_info(self) -> Optional[Dict]:
        """Get device information (if available via FCM)"""
        # Note: FCM doesn't provide device info endpoint
        # This would require additional implementation
        return {
            'device_token': self.device_token[:20] + "..." if self.device_token else None,
            'configured': bool(self.server_key and self.device_token),
            'test_mode': self.test_mode
        }

# Alternative notifier using Pushbullet (fallback option)
class PushbulletNotifier:
    def __init__(self):
        self.notification_config = config.get_notification_config()
        self.pushbullet_config = self.notification_config.get('pushbullet', {})
        self.access_token = self.pushbullet_config.get('access_token')
        self.api_url = "https://api.pushbullet.com/v2/pushes"
        
        # Single notification mode
        self.test_mode = config.is_test_mode()
        
        logger.info("📱 Pushbullet Notifier initialized")
    
    async def send_notification(self, formatted_message: str, message_data: Dict[str, Any]) -> bool:
        """Send single LOUD notification via Pushbullet"""
        if not self.access_token:
            logger.error("❌ Pushbullet access token not configured")
            return False
        
        if self.test_mode:
            logger.info(f"🧪 TEST MODE: Would send Pushbullet notification:\n{formatted_message}")
            return True
        
        try:
            # Extract title from message
            lines = formatted_message.strip().split('\n')
            base_title = lines[0].replace('🔔', '').replace('**', '').strip()
            
            # Create LOUD attention-grabbing notification
            loud_title = f"🚨🔊 URGENT MESSAGE 🔊🚨"
            loud_body = f"""🚨 IMPORTANT TELEGRAM MESSAGE 🚨

{formatted_message}

🔊 CHECK YOUR PHONE NOW! 🔊
⚠️ DON'T IGNORE THIS ALERT ⚠️"""
            
            payload = {
                "type": "note",
                "title": loud_title[:100],
                "body": loud_body[:1000]
            }
            
            headers = {
                "Access-Token": self.access_token,
                "Content-Type": "application/json"
            }
            
            # Send single LOUD notification
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    
                    if response.status == 200:
                        logger.log_notification_sent("Pushbullet", True)
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Pushbullet error {response.status}: {error_text}")
                        return False
        
        except Exception as e:
            logger.error(f"❌ Pushbullet notification error: {e}")
            return False
    
    async def send_test_notification(self) -> bool:
        """Send a single test notification"""
        test_message = """🔔 **Test Notification**
        
📱 **Source**: Message Scraper Test
👤 **From**: System
🕐 **Time**: Now

📝 **Content**:
This is a test notification to verify Pushbullet is working correctly.

---
✅ Pushbullet Test Successful"""
        
        test_data = {
            'id': 'test_' + str(int(time.time())),
            'source': 'test',
            'chat_id': 'test_chat',
            'chat_title': 'Test Chat',
            'sender_name': 'Test System',
            'timestamp': datetime.now(),
            'has_media': False,
            'media_type': None
        }
        
        logger.info("🧪 Sending Pushbullet test notification...")
        result = await self.send_notification(test_message, test_data)
        
        if result:
            logger.info("✅ Pushbullet test notification sent successfully")
        else:
            logger.error("❌ Pushbullet test notification failed")
        
        return result

# Test functions
async def test_fcm_notifier():
    """Test FCM notifier"""
    notifier = FCMNotifier()
    
    # Validate configuration
    config_errors = notifier.validate_config()
    if config_errors:
        logger.error(f"❌ FCM config errors: {config_errors}")
        return False
    
    # Send test notification
    return await notifier.send_test_notification()

async def test_pushbullet_notifier():
    """Test Pushbullet notifier"""
    notifier = PushbulletNotifier()
    
    test_message = "🔔 **Pushbullet Test**\n\nThis is a test notification via Pushbullet."
    test_data = {'id': 'test', 'source': 'test'}
    
    return await notifier.send_notification(test_message, test_data)

if __name__ == "__main__":
    # Test both notifiers
    asyncio.run(test_fcm_notifier())
    # asyncio.run(test_pushbullet_notifier())aa