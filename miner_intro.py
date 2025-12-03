import sys
import time
import random
import os

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
    print("\n\033[92m[SYSTEM] Initializing Apache Data Miner...\033[0m")
    
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
    PROGRESS_BAR_LENGTH = 40
    percent = float(current) * 100 / total
    filled_length = int(PROGRESS_BAR_LENGTH * current // total)
    
    # Visuals
    bar = '█' * filled_length + '░' * (PROGRESS_BAR_LENGTH - filled_length)
    icon = SPINNER[current % 4]
    
    # Cyan colour for the bar
    sys.stdout.write(f"\r\033[96m{icon} {label} [{bar}] {int(percent)}% ({current}/{total})\033[0m")
    sys.stdout.flush()

def run_all():
    clear_screen()
    print_banner()
    loading_animation()

if __name__ == "__main__":
    run_all()