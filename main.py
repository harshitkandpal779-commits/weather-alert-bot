import weather 
import notifier

HIGH_TEMP = 35  # Alert if temp > 35°C
LOW_TEMP = 10   # Alert if temp < 10°C

def main():
    data = weather.get_weather()
    print(f"Current weather in {data['city']}: {data['temp']}°C, {data['condition']}")

    if data['temp'] > HIGH_TEMP:
        subject = f"Weather Alert: Too Hot in {data['city']}!"
        body = f"It is very hot today! Current temp: {data['temp']}°C\nHumidity: {data['humidity']}%\nCondition: {data['condition']}\nFull details: {data}"
        notifier.send_alert(subject, body)

    elif data['temp'] < LOW_TEMP:
        subject = f"Weather Alert: Too Cold in {data['city']}!"
        body = f"It is very cold today! Current temp: {data['temp']}°C\nHumidity: {data['humidity']}%\nCondition: {data['condition']}\nFull details: {data}"
        notifier.send_alert(subject, body)
    else:
        print("Temperature is normal. No alert needed.")

if __name__ == "__main__":
    main()
