# Helper function
class mytext:
    def __init__ (self, filename="", header=""):
        self.filename = filename
        self.header = header
        self.text = header

    def addraw (self, line):
        self.text = self.text + line

    def add (self, line):
        self.addraw (line + "\n")

    def write (self):
        try:
            with open(self.filename, "w") as file:
                file.write (self.text)
        except:
            raise SystemExit (f"Unable to write to the '{self.filename}' file, exiting...")
    
