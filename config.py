from dotenv import load_dotenv 
import os 

load_dotenv()

API_KEY = os.getenv('API_KEY')
SENDER_EMAIL = os.getenv('SENDER_EMAIL')
SENDER_PASSWORD = os.getenv('SENDER_PASSWORD')
RECEIVER_EMAIL = os.getenv('RECEIVER_EMAIL')

CITY = os.getenv('CITY', 'delhi')
BASE_URL = 'http://api.weatherapi.com/v1/current.json'
UNITS = 'metric'
