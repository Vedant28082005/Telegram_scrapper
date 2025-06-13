import google.generativeai as genai
import asyncio
import time
import re
from typing import Dict, Any, Optional
import os
from PIL import Image
import sys

# Add project root to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from src.utils.config import config
from src.utils.logger import logger

class ForexGeminiProcessor:
    def __init__(self):
        self.config = config.get_gemini_config()
        self.message_format_template = config.get('message_format.template', '')
        self.max_tokens = self.config.get('max_tokens', 400)  # Reduced for trading
        self.rate_limit_delay = config.get('system.rate_limit_delay', 5)  # Increased delay
        
        # Check if we're in test mode or API key missing
        self.test_mode = config.is_test_mode()
        
        if not self.config.get('api_key') or self.test_mode:
            logger.warning("⚠️ Gemini API key not set or in test mode - using fallback formatting")
            self.fallback_mode = True
            logger.info("🤖 Forex Gemini AI processor initialized (FALLBACK MODE)")
            return
        
        self.fallback_mode = False
        
        # Initialize Gemini with better error handling
        try:
            genai.configure(api_key=self.config['api_key'])
            
            # Use Flash model by default (most reliable and lowest quota)
            model_name = self.config.get('model', 'gemini-1.5-flash')
            self.text_model = genai.GenerativeModel(model_name)
            self.vision_model = genai.GenerativeModel(self.config.get('vision_model', 'gemini-1.5-flash'))
            
            logger.info(f"🤖 Forex Gemini AI processor initialized with {model_name}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini: {e}")
            logger.warning("⚠️ Switching to fallback mode for forex analysis")
            self.fallback_mode = True
    
    async def process_text_message(self, message_data: Dict[str, Any]) -> str:
        """Process text message for forex trading signals"""
        if self.fallback_mode:
            return self._create_fallback_forex_message(message_data)
        
        start_time = time.time()
        
        try:
            # Create forex-specific prompt
            prompt = self._create_forex_analysis_prompt(message_data)
            
            # Generate response
            response = await self._generate_response(self.text_model, prompt)
            
            processing_time = time.time() - start_time
            logger.log_ai_processing("forex-text", processing_time)
            
            return response
            
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                logger.warning("⏳ Rate limited, using fallback formatting")
            else:
                logger.error(f"❌ Error processing forex text message: {e}")
            return self._create_fallback_forex_message(message_data)
    
    async def process_image_message(self, message_data: Dict[str, Any]) -> str:
        """Process chart image for forex trading signals"""
        if self.fallback_mode:
            return self._create_fallback_forex_message(message_data, "Chart image received")
        
        start_time = time.time()
        
        try:
            # Step 1: Analyze the chart image
            if message_data.get('media_path'):
                chart_analysis = await self._analyze_forex_chart(message_data['media_path'])
                
                # Add analysis to message data
                message_data['chart_analysis'] = chart_analysis
                message_data['content_type'] = 'forex_chart'
            else:
                chart_analysis = "Chart could not be processed"
                message_data['chart_analysis'] = chart_analysis
            
            # Step 2: Format the forex signal with chart analysis
            formatted_message = await self._format_forex_signal(message_data, chart_analysis)
            
            processing_time = time.time() - start_time
            logger.log_ai_processing("forex-chart", processing_time)
            
            return formatted_message
            
        except Exception as e:
            logger.error(f"❌ Error processing forex chart: {e}")
            return self._create_fallback_forex_message(message_data, "Chart analysis failed")
    
    async def _analyze_forex_chart(self, image_path: str) -> str:
        """Analyze forex chart using Gemini Vision with specific trading methodology"""
        try:
            # Load and prepare image
            image = Image.open(image_path)
            
            # Create detailed forex chart analysis prompt
            chart_prompt = """
            You are a professional forex trader analyzing a trading chart. Follow these EXACT instructions to read the chart:

            STEP 1 - IDENTIFY THE INSTRUMENT:
            - Look at the top of the chart for the instrument name
            - Common instruments: XAUUSD (Gold), EURUSD, GBPUSD, USDJPY, etc.
            - If you see "Gold Spot" or "XAU" it means XAUUSD

            STEP 2 - IDENTIFY THE RISK/REWARD TOOL:
            - Look for a colored risk/reward tool on the chart
            - This tool has TWO distinct colored sections:
              * BLUE section = Take Profit (Target) zone
              * RED section = Stop Loss zone
            - The junction/boundary between blue and red colors = Entry Price

            STEP 3 - DETERMINE TRADE DIRECTION:
            - If BLUE section is BELOW the junction = SHORT/SELL trade
            - If BLUE section is ABOVE the junction = LONG/BUY trade
            - The blue section shows where the price is expected to move (target direction)

            STEP 4 - READ PRICE LEVELS:
            - Entry Price = The exact price level at the junction between blue and red
            - Stop Loss = The price level at the far end of the RED section
            - Take Profit = The price level at the far end of the BLUE section
            - Look at the price scale on the right side of the chart for exact numbers

            STEP 5 - IDENTIFY TIMEFRAME:
            - Look at the bottom of the chart for timeframe (15m, 1h, 4h, 1D, etc.)
            - This shows the chart period being displayed

            EXAMPLE ANALYSIS FORMAT:
            **INSTRUMENT**: XAUUSD (Gold)
            **TRADE DIRECTION**: SHORT (because blue section is below junction)
            **ENTRY PRICE**: 3383.00 (junction between blue and red)
            **STOP LOSS**: 3388.00 (far end of red section)
            **TAKE PROFIT**: 3349.00 (far end of blue section)
            **TIMEFRAME**: 15m
            **RISK/REWARD**: 1:6.8 (calculated from levels)

            CRITICAL RULES:
            1. Always identify the colored risk/reward tool first
            2. Entry is ALWAYS at the junction of blue and red
            3. Direction is determined by which way the blue section points
            4. Read exact price levels from the right-side price scale
            5. If no risk/reward tool is visible, look for other entry/exit markers

            NOW ANALYZE THIS CHART:
            Provide your analysis in the exact format above. Be precise with price levels and trade direction.
            """
            
            # Generate chart analysis
            response = self.vision_model.generate_content([chart_prompt, image])
            analysis = response.text.strip()
            
            logger.debug(f"📊 Chart analyzed: {analysis[:150]}...")
            return analysis
            
        except Exception as e:
            logger.error(f"❌ Error analyzing forex chart: {e}")
            return "Unable to analyze chart - manual review required"
    
    async def _format_forex_signal(self, message_data: Dict[str, Any], chart_analysis: str) -> str:
        """Format forex signal with accurate chart analysis"""
        prompt = f"""
        Create a forex trading signal notification based on this professional chart analysis.

        CHART ANALYSIS RESULTS: {chart_analysis}
        ORIGINAL MESSAGE: {message_data.get('text', 'Chart image received')}
        SOURCE: {message_data['source']} ({message_data['chat_title']})
        SENDER: {message_data['sender_name']}
        TIME: {message_data['timestamp']}

        EXTRACT THE EXACT TRADING INFORMATION:
        From the chart analysis, identify:
        1. Instrument (XAUUSD, EURUSD, etc.)
        2. Trade Direction (BUY/SELL based on risk/reward tool)
        3. Entry Price (junction of blue and red sections)
        4. Stop Loss (red section level)
        5. Take Profit (blue section level)
        6. Risk/Reward ratio
        7. Timeframe

        CREATE MOBILE NOTIFICATION IN THIS EXACT FORMAT:
        🔔 **FOREX TRADE SIGNAL**
        
        📈 **Instrument**: [INSTRUMENT]
        💰 **Entry**: [ENTRY_PRICE]
        🛑 **Stop Loss**: [STOP_LOSS]
        🎯 **Take Profit**: [TAKE_PROFIT]
        📊 **Risk/Reward**: [RATIO]
        📱 **Direction**: [BUY/SELL]
        ⏰ **Timeframe**: [TIMEFRAME]
        
        📝 **Analysis**: Chart shows [BRIEF_SETUP_DESCRIPTION]
        👤 **Source**: {message_data['sender_name']} ({message_data['chat_title']})
        
        ---
        🤖 AI Chart Analysis
        ⚡ Ready to Trade!

        REQUIREMENTS:
        - Use EXACT price levels from the chart analysis
        - Keep under 400 characters for mobile
        - Make it immediately actionable
        - Include risk management info
        - Be precise with entry/exit levels
        - Calculate risk/reward ratio if possible

        If the chart analysis shows specific levels (like Entry: 3383, SL: 3388, TP: 3349), use those EXACT numbers.
        """
        
        response = await self._generate_response(self.text_model, prompt)
        return response
    
    def _create_forex_analysis_prompt(self, message_data: Dict[str, Any]) -> str:
        """Create prompt for forex text analysis"""
        return f"""
        Analyze this forex/trading message and extract trading signal information.

        MESSAGE: {message_data['text']}
        SOURCE: {message_data['source']} ({message_data['chat_title']})
        SENDER: {message_data['sender_name']}
        TIME: {message_data['timestamp']}

        EXTRACT TRADING INFORMATION:
        1. **Instrument**: Currency pair or asset (EURUSD, GBPUSD, XAUUSD, etc.)
        2. **Entry Price**: Where to enter the trade
        3. **Stop Loss**: Risk management level
        4. **Take Profit**: Target profit level(s)
        5. **Direction**: BUY/LONG or SELL/SHORT
        6. **Reasoning**: Why this trade setup

        LOOK FOR KEYWORDS:
        - Pairs: EUR/USD, GBP/USD, USD/JPY, XAU/USD, etc.
        - Prices: Numbers with decimals (1.2345, 1950.50, etc.)
        - Actions: BUY, SELL, LONG, SHORT, ENTER, EXIT
        - Levels: STOP, SL, TP, TARGET, SUPPORT, RESISTANCE

        FORMAT AS MOBILE FOREX SIGNAL:
        🔔 **FOREX TRADE SIGNAL**
        
        📈 **Instrument**: [PAIR]
        💰 **Entry**: [PRICE]
        🛑 **Stop Loss**: [PRICE]
        🎯 **Take Profit**: [PRICE]
        📱 **Direction**: [BUY/SELL]
        
        📝 **Analysis**: [WHY THIS TRADE]
        
        ---
        🤖 AI Signal Analysis
        ⚡ Ready to Trade!

        If trading info is not clear, indicate "Signal analysis needed" and provide general market context.
        Keep under 400 characters for mobile notification.
        """
    
    async def _generate_response(self, model, prompt: str) -> str:
        """Generate response from Gemini with rate limiting"""
        try:
            # Add rate limiting delay
            await asyncio.sleep(self.rate_limit_delay)
            
            # Generate response
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=self.max_tokens,
                    temperature=0.3,
                )
            )
            
            return response.text.strip()
            
        except Exception as e:
            logger.error(f"❌ Gemini API error: {e}")
            raise
    
    def _create_fallback_forex_message(self, message_data: Dict[str, Any], error_note: str = "") -> str:
        """Create fallback forex message when AI processing fails with chart context"""
        timestamp = message_data['timestamp'].strftime("%H:%M")
        error_suffix = f" ({error_note})" if error_note else ""
        
        # Try to extract basic info from text
        text_content = message_data.get('text', '')
        
        # Enhanced pattern matching for forex pairs and common terms
        forex_patterns = {
            'pairs': re.findall(r'(?:XAU|XAG|EUR|GBP|USD|JPY|CHF|CAD|AUD|NZD)[\/\-\s]?(?:USD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|GOLD)', text_content.upper()),
            'prices': re.findall(r'\d{4}\.?\d*|\d{1,3}\.\d{4,5}', text_content),  # Better price pattern for forex
            'direction': re.findall(r'(?:BUY|SELL|LONG|SHORT)', text_content.upper())
        }
        
        # Handle Gold/XAUUSD identification
        if 'GOLD' in text_content.upper() or 'XAU' in text_content.upper():
            instrument = "XAUUSD"
        elif forex_patterns['pairs']:
            instrument = forex_patterns['pairs'][0]
        else:
            instrument = "Signal Analysis Needed"
        
        direction = forex_patterns['direction'][0] if forex_patterns['direction'] else "TBD"
        
        if message_data.get('has_media'):
            if message_data.get('requires_chart_analysis', False):
                content = f"📊 Trading chart received - Risk/Reward tool analysis needed{error_suffix}"
                analysis_note = "Look for blue/red risk reward tool: Entry at junction, Blue=Target, Red=StopLoss"
            else:
                content = f"📊 Chart image - Manual analysis required{error_suffix}"
                analysis_note = "Check chart for entry, stop loss, and take profit levels"
        else:
            content = text_content[:200] if text_content else "Trading signal received"
            analysis_note = "Review original message for trading details"
        
        return f"""🔔 **FOREX SIGNAL ALERT**{error_suffix}
        
📈 **Instrument**: {instrument}
📱 **Direction**: {direction}
💰 **Entry**: Manual Review Required
🛑 **Stop Loss**: Check Chart
🎯 **Take Profit**: Check Chart

📝 **Content**: {content}
💡 **Note**: {analysis_note}

📱 **Source**: {message_data['source']} ({message_data['chat_title']})
👤 **From**: {message_data['sender_name']}
🕐 **Time**: {timestamp}

---
⚠️ Manual Analysis Required
📊 Check Risk/Reward Tool Colors"""
    
    async def test_connection(self) -> bool:
        """Test Gemini API connection for forex processing with better error handling"""
        if self.fallback_mode:
            logger.info("✅ Forex processor running in FALLBACK mode (no API needed)")
            return True
        
        # Only test the model we're actually using
        try:
            model_name = self.config.get('model', 'gemini-1.5-flash')
            test_model = genai.GenerativeModel(model_name)
            
            test_prompt = "Say 'FOREX READY' if you can analyze trading signals."
            response = test_model.generate_content(
                test_prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=20,  # Very small for testing
                    temperature=0.1,
                )
            )
            
            if "forex" in response.text.lower() and "ready" in response.text.lower():
                logger.info(f"✅ Forex Gemini API test successful with {model_name}")
                return True
            else:
                logger.warning(f"⚠️ Unexpected response from {model_name}, switching to fallback")
                self.fallback_mode = True
                return True  # Still return True to continue with fallback
            
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "quota" in error_msg.lower():
                logger.warning("⏳ Gemini API quota exceeded - switching to fallback mode")
            elif "404" in error_msg or "not found" in error_msg.lower():
                logger.warning("⚠️ Gemini model not available - switching to fallback mode")
            else:
                logger.warning(f"⚠️ Gemini API error: {error_msg[:100]}... - switching to fallback mode")
            
            self.fallback_mode = True
            return True  # Always return True to continue with fallback

# Test function
async def test_forex_gemini_processor():
    """Test forex Gemini processor functionality"""
    processor = ForexGeminiProcessor()
    
    if not await processor.test_connection():
        return False
    
    # Test forex text processing
    sample_forex_message = {
        'source': 'telegram',
        'chat_title': 'Forex Signals',
        'sender_name': 'TraderBot',
        'timestamp': '2025-06-12 20:15:00',
        'text': 'XAUUSD SELL at 2650.50, Stop Loss: 2665.00, Take Profit: 2620.00. Strong resistance at current level.',
        'has_media': False
    }
    
    try:
        formatted = await processor.process_text_message(sample_forex_message)
        logger.info(f"✅ Forex text processing test successful:\n{formatted}")
        return True
    except Exception as e:
        logger.error(f"❌ Forex text processing test failed: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(test_forex_gemini_processor())