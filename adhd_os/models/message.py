from typing import List, Any, Optional

class Part:
    """
    Represents a part of a message content.
    Mimics google.adk.types.Part (if it existed) or what Runner expects.
    """
    def __init__(self, text: str):
        self.text = text

    def to_dict(self) -> dict:
        return {"text": self.text}

class Message:
    """
    Represents a chat message.
    Mimics google.adk.types.Message or what Runner expects.
    """
    def __init__(self, content: str, role: str = "user"):
        self.content = content
        self.role = role
        self.parts: List[Part] = [Part(text=content)]
    
    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "parts": [p.to_dict() for p in self.parts]
        }
