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