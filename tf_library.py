# Helper function
class mytext:
    def __init__ (self):
        self.text = ""

    def addraw (self, line):
        self.text = self.text + line

    def add (self, line):
        self.addraw (line + "\n")

    
