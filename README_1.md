# Weather Alert Bot 🌦️📧

A simple Python bot that checks real-time weather using WeatherAPI and sends email alerts when the temperature is too high or too low.

### Features
- Fetches live weather data from WeatherAPI
- Checks if temperature crosses thresholds (hot/cold)
- Sends automated email alerts via Gmail SMTP
- Configurable city and thresholds
- Secure using environment variables

### Tech Stack
- Python 3
- WeatherAPI.com
- `requests`, `python-dotenv`
- Gmail SMTP

### Project Structure
```
weather-alert-bot/
├── main.py         # Main logic - checks temp and triggers alert
├── weather.py      # Fetches weather data from API
├── notifier.py     # Sends email alert
├── config.py       # Loads env variables
├── requirements.txt
├── .env.example    # Template for your secrets
└── .gitignore
```

### Setup & Installation

1. **Clone the repo**
   ```bash
   git clone https://github.com/YOUR_USERNAME/weather-alert-bot.git
   cd weather-alert-bot
   ```

2. **Create virtual environment (optional but recommended)**
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   # source venv/bin/activate # Mac/Linux
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**
   Create a `.env` file in root (copy from `.env.example`):
   ```
   API_KEY=your_weatherapi_key
   SENDER_EMAIL=your_email@gmail.com
   SENDER_PASSWORD=your_gmail_app_password
   RECEIVER_EMAIL=receiver_email@gmail.com
   CITY=delhi
   ```
   - Get free API key from https://www.weatherapi.com/
   - For Gmail: Use App Password, not regular password. Enable 2FA -> Generate App Password

5. **Run the bot**
   ```bash
   python main.py
   ```

### How it Works
1. `weather.py` calls WeatherAPI with city and API key
2. Returns temp, humidity, condition
3. `main.py` compares temp with HIGH/LOW thresholds
4. If condition met, `notifier.py` sends email via SMTP

### Future Improvements
- [ ] Add cron job / GitHub Actions for daily automation
- [ ] Add support for rain/thunderstorm alerts
- [ ] Add Telegram/WhatsApp notifications
- [ ] Dockerize the app

### License
MIT

---
Built by Harshit Kandpal

### 🤖 Automate with GitHub Actions

This repo includes a workflow that runs daily at 8 AM IST.

**Setup:**
1. Go to your GitHub repo -> Settings -> Secrets and variables -> Actions
2. Click New repository secret and add these 5 secrets:
   - `API_KEY`
   - `SENDER_EMAIL`
   - `SENDER_PASSWORD`
   - `RECEIVER_EMAIL`
   - `CITY`

3. Go to Actions tab -> Enable workflows -> Run workflow to test.

No server needed!
