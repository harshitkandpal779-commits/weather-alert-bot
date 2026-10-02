import config 
import requests 

def get_weather():
    params = {
        "key": config.API_KEY,
        "q": config.CITY,
        "aqi": "no"
    }
    response = requests.get(config.BASE_URL, params=params)
    response.raise_for_status()
    data = response.json()

    current = data['current']
    return {
        "temp": current['temp_c'],
        "humidity": current['humidity'],
        "condition": current['condition']['text'],
        "city": data['location']['name']
    }

if __name__ == "__main__":
    print(get_weather())
