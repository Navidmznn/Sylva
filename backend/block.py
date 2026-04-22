import tiktoken

class Block:

    def __init__(self, text, is_table):
        self.text = text
        self.is_table = is_table
        self.importance_score = 0
        self.context_size = 0
    
    def set_context_size(self):
        encoding = tiktoken.get_encoding("cl100k_base")
        self.context_size = len(encoding.encode(self.text))

