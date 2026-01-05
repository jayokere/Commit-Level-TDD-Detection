import sys
import time
import random
import os
import threading

# Constants
SPINNER = ['|', '/', '-', '\\']

# Function to clear the console screen
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# Function to print the ASCII art banner
def print_banner():
    # ASCII Art generated for "APACHE MINER"
    banner = [
        r"  █████╗ ██████╗  █████╗  ██████╗██╗  ██╗███████╗    ███╗   ███╗██╗███╗   ██╗███████╗██████╗ ",
        r" ██╔══██╗██╔══██╗██╔══██╗██╔════╝██║  ██║██╔════╝    ████╗ ████║██║████╗  ██║██╔════╝██╔══██╗",
        r" ███████║██████╔╝███████║██║     ███████║█████╗      ██╔████╔██║██║██╔██╗ ██║█████╗  ██████╔╝",
        r" ██╔══██║██╔═══╝ ██╔══██║██║     ██╔══██║██╔══╝      ██║╚██╔╝██║██║██║╚██╗██║██╔══╝  ██╔══██╗",
        r" ██║  ██║██║     ██║  ██║╚██████╗██║  ██║███████╗    ██║ ╚═╝ ██║██║██║ ╚████║███████╗██║  ██║",
        r" ╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝    ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝"
    ]
    
    # Print in bright cyan
    print("\033[96m") 
    for line in banner:
        print(line)
        time.sleep(0.02) # Typing effect
    print("\033[0m") # Reset color

# Simulate a Matrix-style loading animation
def loading_animation(duration=3):
    print("\n\033[92m[SYSTEM] Initialising Apache Data Miner...\033[0m")
    
    end_time = time.time() + duration
    idx = 0
    HEX_STREAM_LENGTH = 60
    CLEAR_LINE_LENGTH = 80
    
    while time.time() < end_time:
        # Generate random hex code stream
        hex_stream = "".join([random.choice("0123456789ABCDEF") for _ in range(HEX_STREAM_LENGTH)])
        sys.stdout.write(f"\r\033[92m{hex_stream} {SPINNER[idx % 4]}\033[0m")
        sys.stdout.flush()
        idx += 1
        time.sleep(0.1)
    
    sys.stdout.write("\r" + " " * CLEAR_LINE_LENGTH + "\r") # Clear line
    print("\033[92m[ACCESS GRANTED] Uplink Established.\033[0m\n")

# Function to update the progress bar during the link resolution process
def update_progress(current, total, label="PROCESSING"):
    # Safety check: prevent division by zero
    if total <= 0:
        total = 1
        
    PROGRESS_BAR_LENGTH = 40
    percent = float(current) * 100 / total
    
    # Ensure we don't exceed 100% visually
    if percent > 100: percent = 100
    
    filled_length = int(PROGRESS_BAR_LENGTH * current // total)
    # Ensure filled length doesn't exceed bar length
    if filled_length > PROGRESS_BAR_LENGTH: filled_length = PROGRESS_BAR_LENGTH
    
    # Visuals
    bar = '█' * filled_length + '░' * (PROGRESS_BAR_LENGTH - filled_length)
    icon = SPINNER[current % 4]
    
    # Cyan colour for the bar
    sys.stdout.write(f"\r\033[96m{icon} {label} [{bar}] {int(percent)}% ({current}/{total})\033[0m")
    sys.stdout.flush()

class ProgressMonitor:
    """
    A thread-safe progress bar that spins constantly (animation) 
    while waiting for the actual tasks (progress) to complete.
    """
    def __init__(self, total, label="PROCESSING"):
        self.total = total if total > 0 else 1
        self.current = 0
        self.label = label
        self.running = False
        self.lock = threading.Lock()
        self.thread = None
        self._tick = 0
        # Flag to track if we have printed a message yet.
        # This helps us decide whether to overwrite the previous line or not.
        self._first_log = True 

    def start(self):
        """Starts the background animation thread."""
        self.running = True
        self.thread = threading.Thread(target=self._animate)
        self.thread.daemon = True 
        self.thread.start()

    def stop(self):
        """Stops the animation and clears the line one last time."""
        self.running = False
        if self.thread:
            self.thread.join()
        sys.stdout.write("\n") 

    def update(self, count):
        """Updates the completion count."""
        self.current = count

    def log(self, message):
        """
        Safely prints a message above the progress bar.
        It maintains a single empty line gap between the logs and the bar,
        but keeps the log messages themselves tightly packed.
        """
        with self.lock:
            # 1. Clear the current progress bar line
            sys.stdout.write("\r\033[K")
            
            # 2. Logic to handle the "Spacer" line
            if not self._first_log:
                # If this isn't the first log, we are sitting below an existing "Empty Gap".
                # We move UP one line (\033[F) and clear it (\033[K).
                # This lets us print the new message directly underneath the previous message.
                sys.stdout.write("\033[F\033[K")
            
            # 3. Print the message
            print(message)
            
            # 4. Print the NEW Spacer line
            print() 
            
            # 5. Mark that we have logged at least once
            self._first_log = False
            
            # 6. Force an immediate redraw of the bar below the spacer
            self._draw()

    def _draw(self):
        """Draws the progress bar."""
        PROGRESS_BAR_LENGTH = 40
        percent = float(self.current) * 100 / self.total
        if percent > 100: percent = 100
        
        filled_length = int(PROGRESS_BAR_LENGTH * self.current // self.total)
        if filled_length > PROGRESS_BAR_LENGTH: filled_length = PROGRESS_BAR_LENGTH
        
        bar = '█' * filled_length + '░' * (PROGRESS_BAR_LENGTH - filled_length)
        icon = SPINNER[self._tick % 4]
        
        sys.stdout.write(f"\r\033[96m{icon} {self.label} [{bar}] {int(percent)}% ({self.current}/{self.total})\033[0m")
        sys.stdout.flush()

    def _animate(self):
        """The loop that runs in the background thread."""
        while self.running:
            with self.lock:
                self._draw()
            time.sleep(0.1) 
            self._tick += 1

def run_all():
    clear_screen()
    print_banner()
    loading_animation()

if __name__ == "__main__":
    run_all()