import smtplib
from email.message import EmailMessage
import config 

def send_alert(subject, body):
    msg = EmailMessage()
    msg['Subject'] = subject 
    msg['From'] = config.SENDER_EMAIL
    msg['To'] = config.RECEIVER_EMAIL
    msg.set_content(body)

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(config.SENDER_EMAIL, config.SENDER_PASSWORD)
    server.send_message(msg)
    print("Email sent successfully!")
    server.quit()

if __name__ == "__main__":
    send_alert("Hello from the Weather Bot", "Test alert - your weather bot is working!")
