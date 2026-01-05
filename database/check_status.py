from database.db import (
    get_all_mined_project_names,
    get_java_projects_to_mine,
    get_python_projects_to_mine,
    get_cpp_projects_to_mine,
    get_db_connection
)
import os
from dotenv import load_dotenv, find_dotenv

def check_connection():
    db = get_db_connection()
    # The 'address' property reveals where the client is actually pointing
    print(f"\n🔗 CONNECTED TO: {db.client.address}")
    
    # Check the nodes to see if it's a cluster (Cloud) or standalone (Local)
    print(f"📡 NODES: {db.client.nodes}")

def check_env():
    # Force reload of the .env file
    load_dotenv(find_dotenv(), override=True)

    conn_str = os.getenv('MONGODB_CONNECTION_STRING')

    print(f"Loaded Connection String: {conn_str}")

    if conn_str and "localhost" in conn_str:
        print("📟 Python is ready to connect to MongoDB local db.")
    elif conn_str:
        print("✅ Python is ready to collect to MongoDB Server.")
    else:
        print("❌ FAILURE: No connection string found in environment.")

def check_status():
    print("Connecting to database and calculating quotas...\n")
    
    # 1. Get the set of names for projects that have ACTUAL data mined
    # This queries the 'mined-commits-temp' collection
    already_mined_names = get_all_mined_project_names()
    
    # 2. Get the full lists of candidate projects from 'mined-repos'
    java_candidates = get_java_projects_to_mine()
    python_candidates = get_python_projects_to_mine()
    cpp_candidates = get_cpp_projects_to_mine()
    
    # 3. Helper function to count intersections
    def get_counts(candidates, mined_set):
        mined_count = 0
        for project in candidates:
            if project['name'] in mined_set:
                mined_count += 1
        return mined_count, len(candidates)

    # 4. Calculate stats
    j_mined, j_total = get_counts(java_candidates, already_mined_names)
    p_mined, p_total = get_counts(python_candidates, already_mined_names)
    c_mined, c_total = get_counts(cpp_candidates, already_mined_names)
    
    total_mined = j_mined + p_mined + c_mined
    total_avail = j_total + p_total + c_total

    # 5. Print Table
    print(f"{'LANGUAGE':<10} | {'MINED':<10} | {'AVAILABLE':<10} | {'STATUS'}")
    print("-" * 55)
    print(f"{'Java':<10} | {j_mined:<10} | {j_total:<10} | {j_mined/60*100:.1f}% of Target (60)")
    print(f"{'Python':<10} | {p_mined:<10} | {p_total:<10} | {p_mined/60*100:.1f}% of Target (60)")
    print(f"{'C++':<10} | {c_mined:<10} | {c_total:<10} | {c_mined/60*100:.1f}% of Target (60)")
    print("-" * 55)
    print(f"{'TOTAL':<10} | {total_mined:<10} | {total_avail:<10} |")

def full_check():
    check_env()
    check_connection()
    check_status()

def standard_check():
    check_connection()
    check_status()
    
def ask_user():
    # Print the menu once
    print(""" \nHere are the available checks:
            1. Environment and Database Check (full)
            2. Database Status Check (standard) 
            3. environment Check only (env)
            4. Exit
            """)

    # Loop that continues until a valid choice is made
    while True:
        response = input("What type of check would you like to perform? ").strip().lower()

        if response == "env" or response == "3":
            print("Performing Environment Check...")
            check_env()
            break  # Exit the loop after a valid choice
            
        elif response == "standard" or response == "2":
            print("\nPerforming Standard Database Status Check...")
            standard_check()
            break
            
        elif response == "full" or response == "1":
            print("\nPerforming Full Environment and Database Check...")
            full_check()
            break
            
        elif response == "exit" or response == "4":
            print("Exiting without performing any checks.")
            break
            
        else:
            # If invalid, just print an invalid message. Loop continues.
            print("Invalid option. Please try again (e.g., type '1' or 'full').")
    
    

if __name__ == "__main__":
    response = input("Would you like to perform a full environment and database check? (y/n): ")
    if response.lower() == "y":
        full_check()
    else:
        ask_user()