import tiktoken

class Block:

    def __init__(self, text, number, gap_to_next, page):
        self.text = text
        self.number = number
        self.importance_score = 0
        self.gap_to_next =  gap_to_next
        self.page = page
        self.next_block = None
        self.prev_block = None
        self.lines = text.splitlines()
        self.remove_priority = None


        
    def merge(self, neighbour):
        if self.next_block != neighbour and self.prev_block != neighbour:
            return False
        
        self.importance_score += neighbour.importance_score

        if neighbour == self.next_block:
            self.next_block = neighbour.next_block
            self.text += '\n' + neighbour.text
            self.lines.extend(neighbour.lines)
            self.gap_to_next = neighbour.gap_to_next
            if self.next_block is not None:
                self.next_block.prev_block = self
        else:
            self.text = neighbour.text + '\n' + self.text
            self.lines = neighbour.lines + self.lines
            self.prev_block = neighbour.prev_block
            self.number = neighbour.number
            if self.prev_block is not None:
                self.prev_block.next_block = self


        neighbour.next_block = None
        neighbour.prev_block = None

        return True
    

    def set_context_size(self):
        encoding = tiktoken.get_encoding("cl100k_base")
        self.context_size = len(encoding.encode(self.text))


class Line:

    def __init__(self, text, top, bottom, font_size, font_name, gap_to_next, page):
        self.text = text
        self.top = top
        self.bottom = bottom
        self.gap_to_next = gap_to_next
        self.page = page
        self.font_size = font_size
        self.font_name = font_name
        self.is_header = False
        self.is_junk = False