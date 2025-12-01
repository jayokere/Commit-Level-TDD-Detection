import sys
import time
import random
import os

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

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
    spinner = ['|', '/', '-', '\\']
    idx = 0
    
    while time.time() < end_time:
        # Generate random hex code stream
        hex_stream = "".join([random.choice("0123456789ABCDEF") for _ in range(60)])
        sys.stdout.write(f"\r\033[92m{hex_stream} {spinner[idx % 4]}\033[0m")
        sys.stdout.flush()
        idx += 1
        time.sleep(0.1)
    
    sys.stdout.write("\r" + " " * 80 + "\r") # Clear line
    print("\033[92m[ACCESS GRANTED] Uplink Established.\033[0m\n")

# Function to update the progress bar during the link resolution process
def update_progress(current, total):
    percent = float(current) * 100 / total
    bar_length = 40
    filled_length = int(bar_length * current // total)
    
    # Visuals
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    spinner = ['|', '/', '-', '\\']
    icon = spinner[current % 4]
    
    # Cyan colour for the bar
    sys.stdout.write(f"\r\033[96m{icon} RESOLVING [{bar}] {int(percent)}% ({current}/{total})\033[0m")
    sys.stdout.flush()

def runAll():
    clear_screen()
    print_banner()
    loading_animation()

if __name__ == "__main__":
    runAll()