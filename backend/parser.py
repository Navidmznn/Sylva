import anthropic
from dotenv import load_dotenv
import os

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

while True:
    user = input("You: ")
    if user == "exit":
        break
    
    response = client.messages.create(model="claude-opus-4-6",
                                      max_tokens=2000,
                                      messages=user)
    
    print(response.content[0].text)
    