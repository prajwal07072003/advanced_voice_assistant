import random
import sys
import time
import os.path
import pickle
import re
import logging
from datetime import datetime, timedelta
import pyttsx3
import speech_recognition as sr
import webbrowser
import threading
import requests
import cohere
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, QLabel, QVBoxLayout,
                             QHBoxLayout, QComboBox, QScrollArea, QTextEdit, QSizePolicy,
                             QFrame, QGraphicsDropShadowEffect)
from PyQt5.QtGui import (QPixmap, QMovie, QFont, QColor, QLinearGradient,
                         QPalette, QPainter, QBrush, QFontMetrics)
from PyQt5.QtCore import Qt, QMetaObject, Q_ARG, pyqtSignal, QObject, QPoint

# Set up logging
logging.basicConfig(
    filename='friday.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Memory and configuration
memory = {
    "user_name": None,
    "preferences": {},
    "last_topics": [],
    "calendar_service": None
}


class Config:
    COHERE_API_KEY = "2Ab373vipaUxWwCXwN2*************"
    OPENWEATHER_API_KEY = "30d4741c779ba94c470ca1*****5390a"
    AVATAR_IMAGE = "avatar.png"
    MIC_ANIMATION = "Bold Beats.gif"
    TIMEZONE = "Asia/Kolkota"


# Initialize services
co = cohere.Client(Config.COHERE_API_KEY)
recognizer = sr.Recognizer()
engine = pyttsx3.init()
is_speaking = False
is_muted = False
conversation_history = []

# Voice setup
voice_map = {v.name: v.id for v in engine.getProperty('voices')}
engine.setProperty('voice', list(voice_map.values())[0])
engine.setProperty('rate', 160)
engine.setProperty('volume', 1.0)


def extract_cohere_response(response):
    """Safely extract text from Cohere API response"""
    try:
        if not response or not hasattr(response, 'generations'):
            logging.error("Invalid Cohere response object")
            return "Sorry, I didn't get a valid response."

        if not response.generations:
            logging.warning("Empty generations in Cohere response")
            return "The AI didn't generate any response."

        first_gen = response.generations[0]
        reply = getattr(first_gen, 'text', '').strip()
        return reply if reply else "I didn't get a text response."

    except Exception as e:
        logging.error(f"Cohere response extraction failed: {str(e)}")
        return "I'm having trouble processing that right now."


def validate_conversation_history(history):
    """Ensure history contains valid message formats"""
    valid_history = []
    for msg in history:
        if (isinstance(msg, dict) and
                'role' in msg and
                'content' in msg and
                isinstance(msg['content'], str)):
            valid_history.append(msg)
        else:
            logging.warning(f"Invalid message format in history: {msg}")
    return valid_history


def setup_google_calendar():
    """Set up Google Calendar API credentials"""
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    creds = None

    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('calendar', 'v3', credentials=creds)


def add_calendar_event(summary, start_time, duration=60, description=""):
    """Add an event to Google Calendar"""
    try:
        if not memory["calendar_service"]:
            memory["calendar_service"] = setup_google_calendar()

        end_time = start_time + timedelta(minutes=duration)

        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': Config.TIMEZONE,
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': Config.TIMEZONE,
            },
        }

        event = memory["calendar_service"].events().insert(
            calendarId='primary',
            body=event
        ).execute()

        return f"Added event: {summary} at {start_time.strftime('%I:%M %p on %B %d')}"
    except Exception as e:
        logging.error(f"Calendar error: {str(e)}")
        return "Sorry, I couldn't add that event to your calendar."


def get_upcoming_events(days=7):
    """Get upcoming events from Google Calendar"""
    try:
        if not memory["calendar_service"]:
            memory["calendar_service"] = setup_google_calendar()

        now = datetime.utcnow().isoformat() + 'Z'
        end_date = (datetime.utcnow() + timedelta(days=days)).isoformat() + 'Z'

        events_result = memory["calendar_service"].events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=end_date,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        if not events:
            return f"You don't have any events in the next {days} days."

        event_list = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            start_time = datetime.fromisoformat(start)
            time_str = start_time.strftime('%I:%M %p on %B %d')
            event_list.append(f"- {event['summary']} at {time_str}")

        return "Here are your upcoming events:\n" + "\n".join(event_list)
    except Exception as e:
        logging.error(f"Calendar error: {str(e)}")
        return "Sorry, I couldn't check your calendar."


def extract_city(query):
    """Extract city name from weather query"""
    try:
        match = re.search(r'(weather|forecast|temperature).*(in|for|at)\s+([a-zA-Z\s]+)', query, re.IGNORECASE)
        if match:
            return match.group(3).strip()

        match = re.search(r'(weather|forecast)\s+([a-zA-Z\s]+)', query, re.IGNORECASE)
        if match:
            return match.group(2).strip()

        return ""
    except Exception as e:
        logging.error(f"Error extracting city: {str(e)}")
        return ""


def remember_info(query):
    """Store personal information from user input"""
    try:
        name_match = re.search(r'(my name is|i am|i\'
                               r''m|call me)\s+([a-zA-Z]+)', query, re.IGNORECASE)
        if name_match:
            name = name_match.group(2).strip()
            memory["user_name"] = name
            return f"Got it, {name}! I'll remember that."

        pref_match = re.search(r'(i (like|love|hate|dislike)\s+(.+))', query, re.IGNORECASE)
        if pref_match:
            item = pref_match.group(3).strip()
            sentiment = pref_match.group(2).strip()
            memory["preferences"][item] = sentiment
            return f"Noted that you {sentiment} {item}."

        return None
    except Exception as e:
        logging.error(f"Error remembering info: {str(e)}")
        return None


def recall_info(query):
    """Retrieve stored personal information"""
    try:
        query = query.lower()

        if any(phrase in query for phrase in ["my name", "what am i called", "what's my name"]):
            if memory.get("user_name"):
                return f"Your name is {memory['user_name']}!"
            return "I don't know your name yet. Tell me your name?"

        for item, sentiment in memory.get("preferences", {}).items():
            if item.lower() in query:
                return f"You told me you {sentiment} {item}."

        return None
    except Exception as e:
        logging.error(f"Error recalling info: {str(e)}")
        return None


def tell_joke():
    jokes = [
        "Why don't scientists trust atoms? Because they make up everything!",
        "Did you hear about the mathematician who's afraid of negative numbers? He'll stop at nothing to avoid them.",
        "Why don't skeletons fight each other? They don't have the guts.",
        "I told my wife she was drawing her eyebrows too high. She looked surprised.",
        "What do you call a fake noodle? An impasta!"
    ]
    return random.choice(jokes)


def get_weather(city):
    try:
        URL = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={Config.OPENWEATHER_API_KEY}&units=metric"
        response = requests.get(URL, timeout=5)
        data = response.json()
        if data["cod"] == 200:
            temp = data["main"]["temp"]
            desc = data["weather"][0]["description"].capitalize()
            return f"The weather in {city} is {desc} with a temperature of {temp}°C."
        return f"Sorry, I couldn't find weather for {city}."
    except Exception as e:
        logging.error(f"Weather error: {str(e)}")
        return "Unable to retrieve weather information."


def parse_natural_date(text):
    text = text.lower()
    now = datetime.now()

    if "today" in text:
        date = now
    elif "tomorrow" in text:
        date = now + timedelta(days=1)
    elif "next week" in text:
        date = now + timedelta(weeks=1)
    elif "next month" in text:
        date = now.replace(month=now.month + 1)
    else:
        date = now

    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        period = time_match.group(3).lower() if time_match.group(3) else ''

        if period == 'pm' and hour < 12:
            hour += 12
        elif period == 'am' and hour == 12:
            hour = 0

        date = date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    return date


def detect_intent(query):
    if not query:
        return "unknown"

    query = query.lower()
    if re.search(r'\b(open|go to|visit|navigate to)\s+(.+?)\s?(website|site|page)?\b', query):
        return "open_website"

    if re.search(r'\b(add|create|schedule|set) (event|meeting|appointment|reminder)\b', query):
        return "add_event"
    if re.search(r'\b(show|view|list|what are) (my|upcoming) (events|meetings|appointments)\b', query):
        return "view_events"
    if re.search(r'\b(hello|hi|hey|greetings|sup|what\'?s? up)\b', query):
        return "greet"
    if re.search(r'\b(time|what time is it|current time)\b', query):
        return "time"
    if re.search(r'\b(date|today\'?s? date|what\'?s? the date)\b', query):
        return "date"
    if re.search(r'\b(search|look up|find|google)\b', query):
        return "search"
    if re.search(r'\b(weather|temperature|forecast|how hot|cold|rain|snow)\b', query):
        return "weather"
    if re.search(r'\b(exit|quit|bye|goodbye|see you|stop)\b', query):
        return "exit"
    if re.search(r'\b(tell me a joke|make me laugh|funny)\b', query):
        return "joke"
    if re.search(r'\b(help|what can you do|assistance)\b', query):
        return "help"

    return "ai"


def speak(text):
    global is_speaking, is_muted
    if is_muted:
        return
    if is_speaking:
        engine.stop()
    is_speaking = True
    engine.say(text)
    engine.runAndWait()
    is_speaking = False


def listen():
    try:
        with sr.Microphone() as source:
            logging.info("Listening...")
            recognizer.adjust_for_ambient_noise(source, duration=1)
            audio = recognizer.listen(source, timeout=8, phrase_time_limit=10)

            try:
                query = recognizer.recognize_google(audio).lower()
                logging.info(f"User said: {query}")
                return query
            except sr.UnknownValueError:
                logging.warning("Could not understand audio")
                return ""
            except sr.RequestError as e:
                logging.error(f"Speech recognition error: {e}")
                return ""

    except sr.WaitTimeoutError:
        logging.warning("Listening timed out")
        return ""
    except Exception as e:
        logging.error(f"Listening error: {e}")
        return ""


def change_voice(name):
    if name in voice_map:
        engine.setProperty('voice', voice_map[name])


def open_website(query):
    """Extract website name and open it in browser"""
    try:
        # Extract website name from query
        match = re.search(r'\b(open|go to|visit|navigate to)\s+(.+?)\s?(website|site|page)?\b', query, re.IGNORECASE)
        if not match:
            return "I didn't catch which website you want to open."

        site_name = match.group(2).strip()

        # Map common names to URLs
        website_map = {
            'google': 'https://www.google.com',
            'youtube': 'https://www.youtube.com',
            'facebook': 'https://www.facebook.com',
            'twitter': 'https://www.twitter.com',
            'github': 'https://www.github.com',
            'amazon': 'https://www.amazon.com',
            'wikipedia': 'https://www.wikipedia.org',
            'reddit': 'https://www.reddit.com'
        }

        # Check if it's a known site
        if site_name.lower() in website_map:
            url = website_map[site_name.lower()]
        else:
            # Try to construct URL from name
            if not site_name.startswith(('http://', 'https://', 'www.')):
                site_name = 'https://www.' + site_name
            url = re.sub(r'\s+', '', site_name)  # Remove spaces

        # Open in browser
        webbrowser.open(url)
        return f"Opening {url}"

    except Exception as e:
        logging.error(f"Error opening website: {str(e)}")
        return "Sorry, I couldn't open that website."

class GradientWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)

    def setGradient(self, color1, color2):
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, color1)
        gradient.setColorAt(1.0, color2)
        palette = self.palette()
        palette.setBrush(QPalette.Window, QBrush(gradient))
        self.setPalette(palette)


class Communicate(QObject):
    update_signal = pyqtSignal(str, str)
    status_signal = pyqtSignal(str)
    button_signal = pyqtSignal(bool)
    speak_signal = pyqtSignal(str)
    animation_signal = pyqtSignal(bool)


class FridayApp(GradientWidget):
    def __init__(self):
        super().__init__()
        self.is_running = True
        self.setup_ui()
        self.setup_shadows()
        threading.Thread(target=self.initialize_calendar_service, daemon=True).start()

    def initialize_calendar_service(self):
        try:
            memory["calendar_service"] = setup_google_calendar()
            self.comm.status_signal.emit("Status: Connected to Google Calendar")
        except Exception as e:
            logging.error(f"Calendar init error: {str(e)}")
            self.comm.status_signal.emit("Status: Calendar connection failed")

    def setup_ui(self):
        self.setWindowTitle("Friday - AI Assistant")
        self.setGeometry(200, 200, 1000, 800)
        self.setGradient(QColor(20, 30, 48), QColor(36, 59, 85))

        self.comm = Communicate()
        self.comm.update_signal.connect(self.add_message)
        self.comm.status_signal.connect(self.update_status)
        self.comm.button_signal.connect(self.toggle_buttons)
        self.comm.speak_signal.connect(speak)
        self.comm.animation_signal.connect(self.toggle_animation)

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(15)

        self.setup_top_bar()
        self.setup_chat_area()
        self.setup_controls()
        self.setup_input_area()

        self.setLayout(self.layout)

    def setup_top_bar(self):
        top_bar = QHBoxLayout()
        top_bar.setSpacing(15)

        self.avatar = QLabel()
        try:
            pixmap = QPixmap(Config.AVATAR_IMAGE).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            circular_pixmap = QPixmap(pixmap.size())
            circular_pixmap.fill(Qt.transparent)
            painter = QPainter(circular_pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QBrush(pixmap))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(0, 0, 80, 80)
            painter.end()
            self.avatar.setPixmap(circular_pixmap)
        except:
            self.avatar.setText("Avatar")
            self.avatar.setStyleSheet("background: #303F9F; color: white; border-radius: 40px;")
        self.avatar.setFixedSize(80, 80)
        top_bar.addWidget(self.avatar)

        self.title = QLabel("Friday - Your AI Assistant")
        self.title.setFont(QFont("Montserrat", 24, QFont.Bold))
        self.title.setStyleSheet("color: #40E0D0;")
        self.title.setAlignment(Qt.AlignLeft)
        top_bar.addWidget(self.title)
        top_bar.addStretch()

        self.status = QLabel("Status: Ready")
        self.status.setFont(QFont("Montserrat", 10))
        self.status.setStyleSheet("color: #AAAAAA; padding: 4px;")
        self.status.setAlignment(Qt.AlignRight)

        self.layout.addLayout(top_bar)
        self.layout.addWidget(self.status)

    def setup_chat_area(self):
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout()
        self.chat_layout.setContentsMargins(15, 15, 15, 15)
        self.chat_layout.setSpacing(10)
        self.chat_layout.addStretch(1)
        self.chat_container.setLayout(self.chat_layout)
        self.scroll_area.setWidget(self.chat_container)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: rgba(30, 30, 46, 0.7);
                border-radius: 12px;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(42, 42, 42, 0.5);
                width: 12px;
                border-radius: 6px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: #40E0D0;
                min-height: 30px;
                border-radius: 6px;
            }
        """)
        self.scroll_area.setMinimumHeight(400)
        self.layout.addWidget(self.scroll_area)

        self.mic = QLabel()
        try:
            self.movie = QMovie(Config.MIC_ANIMATION)
            self.mic.setMovie(self.movie)
        except:
            self.mic.setText("🎤")
            self.mic.setStyleSheet("font-size: 48px;")
        self.mic.setAlignment(Qt.AlignCenter)
        self.mic.setFixedHeight(100)
        self.mic.setStyleSheet("background: transparent;")
        self.layout.addWidget(self.mic)

    def setup_controls(self):
        controls = QHBoxLayout()
        controls.setSpacing(15)

        self.button = QPushButton("🎤 Speak with Friday")
        self.button.setFont(QFont("Montserrat", 12, QFont.Bold))
        self.button.setFixedHeight(45)
        self.button.setStyleSheet("""
            QPushButton {
                background-color: #1E90FF;
                color: white;
                padding: 10px 20px;
                border-radius: 8px;
                min-width: 180px;
            }
            QPushButton:hover { background-color: #1a7fd9; }
            QPushButton:disabled { background-color: #555555; color: #AAAAAA; }
            QPushButton:pressed { background-color: #1560BD; }
        """)
        self.button.clicked.connect(self.handle_click)
        controls.addWidget(self.button)

        self.voice_menu = QComboBox()
        self.voice_menu.setFont(QFont("Montserrat", 10))
        self.voice_menu.setFixedHeight(35)
        self.voice_menu.setStyleSheet("""
            QComboBox {
                background-color: rgba(42, 42, 42, 0.7);
                color: white;
                padding: 5px 15px;
                border-radius: 6px;
                border: 1px solid #40E0D0;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background-color: rgba(42, 42, 42, 0.9);
                color: white;
                selection-background-color: #40E0D0;
                border-radius: 6px;
                border: 1px solid #40E0D0;
            }
        """)
        self.voice_menu.addItems(voice_map.keys())
        self.voice_menu.currentTextChanged.connect(change_voice)
        controls.addWidget(self.voice_menu)

        self.layout.addLayout(controls)

    def setup_input_area(self):
        input_frame = QFrame()
        input_frame.setStyleSheet("background: transparent;")
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(10)

        self.text_input = QTextEdit()
        self.text_input.setFixedHeight(60)
        self.text_input.setStyleSheet("""
            QTextEdit {
                background-color: rgba(42, 42, 42, 0.7);
                color: white;
                border: 1px solid #40E0D0;
                padding: 15px;
                border-radius: 8px;
                font-family: 'Montserrat';
                font-size: 14px;
            }
        """)
        self.text_input.setFont(QFont("Montserrat", 12))
        self.text_input.setPlaceholderText("Type your message here...")
        input_layout.addWidget(self.text_input)

        self.send_button = QPushButton("➤")
        self.send_button.setFont(QFont("Montserrat", 14, QFont.Bold))
        self.send_button.setFixedSize(60, 60)
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #40E0D0;
                color: black;
                border-radius: 8px;
                font-size: 16px;
            }
            QPushButton:hover { background-color: #38c9b8; }
            QPushButton:disabled { background-color: #555555; color: #AAAAAA; }
            QPushButton:pressed { background-color: #30B2A0; }
        """)
        self.send_button.clicked.connect(self.handle_text_input)
        input_layout.addWidget(self.send_button)

        self.layout.addWidget(input_frame)

    def setup_shadows(self):
        def add_shadow(widget, radius=10, offset=(0, 0)):
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(radius)
            shadow.setColor(QColor(0, 0, 0, 150))
            shadow.setOffset(*offset)
            widget.setGraphicsEffect(shadow)

        add_shadow(self.avatar, 15, (3, 3))
        add_shadow(self.title, 5, (1, 1))
        add_shadow(self.scroll_area, 20, (0, 5))
        add_shadow(self.button, 10, (2, 2))
        add_shadow(self.send_button, 10, (2, 2))
        add_shadow(self.text_input, 5, (1, 1))

    def add_message(self, text, sender):
        if not self.is_running:
            return

        message_frame = QFrame()
        message_frame.setStyleSheet("background: transparent;")

        message_layout = QHBoxLayout(message_frame)
        if sender == "You":
            message_layout.setContentsMargins(150, 5, 0, 5)
            message_layout.setAlignment(Qt.AlignRight)
        else:
            message_layout.setContentsMargins(0, 5, 150, 5)
            message_layout.setAlignment(Qt.AlignLeft)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(QFont("Montserrat", 12))
        label.setMargin(12)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        fm = QFontMetrics(label.font())
        text_width = fm.width(text) + 40
        max_width = int(self.width() * 0.7)
        min_width = min(text_width, max_width)

        label.setMinimumWidth(int(min_width))
        label.setMaximumWidth(int(max_width))

        if sender == "You":
            label.setStyleSheet("""
                QLabel {
                    background-color: #DCF8C6;
                    color: #000000;
                    border-radius: 12px;
                    border-bottom-right-radius: 0;
                    padding: 8px 12px;
                }
            """)
        else:
            label.setStyleSheet("""
                QLabel {
                    background-color: #303F9F;
                    color: #FFFFFF;
                    border-radius: 12px;
                    border-bottom-left-radius: 0;
                    padding: 8px 12px;
                }
            """)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(3, 3)
        label.setGraphicsEffect(shadow)

        message_layout.addWidget(label)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, message_frame)

        label.adjustSize()
        message_frame.adjustSize()

        QApplication.processEvents()
        scroll_bar = self.scroll_area.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def update_status(self, text):
        if self.is_running:
            self.status.setText(text)

    def toggle_buttons(self, enabled):
        if self.is_running:
            self.button.setEnabled(enabled)
            self.send_button.setEnabled(enabled)

    def toggle_animation(self, start):
        if self.is_running:
            if start:
                if hasattr(self, 'movie'):
                    self.movie.start()
            else:
                if hasattr(self, 'movie'):
                    self.movie.stop()

    def handle_click(self):
        if not self.is_running:
            return
        self.comm.animation_signal.emit(True)
        self.comm.status_signal.emit("Status: Listening...")
        self.comm.button_signal.emit(False)
        threading.Thread(target=self.process_voice_query, daemon=True).start()

    def handle_text_input(self):
        if not self.is_running:
            return
        query = self.text_input.toPlainText().strip()
        if query:
            self.text_input.clear()
            self.comm.update_signal.emit(query, "You")
            self.comm.status_signal.emit("Status: Thinking...")
            self.comm.button_signal.emit(False)
            threading.Thread(target=self.process_text_query, args=(query,), daemon=True).start()

    def get_response(self, query):
        """Main method to process user input and generate responses"""
        try:
            # First try to recall personal info
            recall_response = recall_info(query)
            if recall_response:
                return recall_response

            # Then try to remember new info
            memory_response = remember_info(query)
            if memory_response:
                return memory_response

            intent = detect_intent(query)

            if intent == "open_website":
                return open_website(query)

            if memory["user_name"] and intent == "greet":
                return f"Hello {memory['user_name']}! How can I help you today?"

            if intent == "joke":
                return tell_joke()
            elif intent == "help":
                return """I can help you with:
                - Time and date information
                - Weather forecasts
                - Web searches
                - Jokes and conversation
                - Calendar management
                - And much more!"""
            elif intent == "greet":
                return "Hello! How can I assist you today?"
            elif intent == "time":
                return datetime.now().strftime("The time is %I:%M %p")
            elif intent == "date":
                return datetime.now().strftime("Today is %A, %B %d, %Y")
            elif intent == "weather":
                city = extract_city(query)
                if not city:
                    speak("For which city?")
                    city = listen()
                return get_weather(city) if city else "I couldn't get the city name."
            elif intent == "exit":
                return "Goodbye! Have a great day!"
            elif intent == "add_event":
                speak("What's the event about?")
                summary = listen()
                if not summary:
                    return "I didn't get the event details."

                speak("When is this event? (For example: tomorrow at 3 PM)")
                time_str = listen()
                if not time_str:
                    return "I didn't get the event time."

                try:
                    start_time = parse_natural_date(time_str)
                    return add_calendar_event(summary, start_time)
                except Exception as e:
                    logging.error(f"Time parsing error: {str(e)}")
                    return "Sorry, I couldn't schedule that event."
            elif intent == "view_events":
                return get_upcoming_events()
            else:
                # Validate and trim conversation history
                global conversation_history
                conversation_history = validate_conversation_history(conversation_history[-8:])

                # Build prompt
                prompt_lines = [
                    "You are Friday, a helpful AI assistant with a friendly personality.",
                    "You're knowledgeable, concise, and try to be helpful while maintaining a natural conversation flow.",
                    "\nConversation History:"
                ]

                for exchange in conversation_history:
                    role = "User" if exchange["role"] == "user" else "Friday"
                    prompt_lines.append(f"{role}: {exchange['content']}")

                prompt_lines.append(f"User: {query}")
                prompt_lines.append("Friday:")
                prompt = "\n".join(prompt_lines)

                # Make API call
                response = co.generate(
                    model='command-r-plus',
                    prompt=prompt,
                    max_tokens=400,
                    temperature=0.7,
                    p=0.9
                )

                # Process response
                reply = extract_cohere_response(response)
                reply = re.sub(r'^Friday:', '', reply).strip()

                # Update conversation history
                conversation_history.append({"role": "user", "content": query})
                conversation_history.append({"role": "assistant", "content": reply})

                return reply

        except Exception as e:
            logging.error(f"Response generation failed: {str(e)}")
            return "I'm experiencing some technical difficulties. Please try again later."

    def process_voice_query(self):
        if not self.is_running:
            return

        query = listen()
        self.comm.animation_signal.emit(False)

        if not self.is_running:
            return

        if query:
            self.comm.update_signal.emit(query, "You")
            self.comm.status_signal.emit("Status: Thinking...")
            response = self.get_response(query)
            if not self.is_running:
                return

            self.comm.update_signal.emit(response, "Friday")
            self.comm.speak_signal.emit(response)

            if detect_intent(query) == "search":
                if not self.is_running:
                    return
                self.comm.status_signal.emit("Status: Listening for search term...")
                self.comm.animation_signal.emit(True)
                term = listen()
                self.comm.animation_signal.emit(False)
                if term and self.is_running:
                    self.comm.update_signal.emit(term, "You")
                    webbrowser.open(f"https://www.google.com/search?q={term}")
                    self.comm.speak_signal.emit(f"Here are results for {term}")
            elif detect_intent(query) == "exit":
                if self.is_running:
                    self.comm.speak_signal.emit("Goodbye! Have a great day!")
                    self.close()

        if self.is_running:
            self.comm.status_signal.emit("Status: Ready")
            self.comm.button_signal.emit(True)

    def process_text_query(self, query):
        if not self.is_running:
            return

        response = self.get_response(query)
        if not self.is_running:
            return

        self.comm.update_signal.emit(response, "Friday")
        self.comm.speak_signal.emit(response)

        if self.is_running:
            self.comm.status_signal.emit("Status: Ready")
            self.comm.button_signal.emit(True)

    def closeEvent(self, event):
        self.is_running = False
        for thread in threading.enumerate():
            if thread != threading.main_thread():
                thread.join(timeout=0.1)
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    font = QFont("Montserrat", 10)
    app.setFont(font)
    window = FridayApp()
    window.show()
    window.comm.update_signal.emit("Hello! I'm Friday. How can I help you today?", "Friday")
    window.comm.speak_signal.emit("Hello! I'm Friday. How can I help you today?")
    ret = app.exec_()
    window.is_running = False
    sys.exit(ret)
