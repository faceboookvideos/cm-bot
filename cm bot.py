import time
import pandas as pd
import os
import threading
import sys
import ctypes
from playwright.sync_api import sync_playwright
from datetime import datetime

# উইন্ডোজ টার্মিনালে কালার সাপোর্ট এনাবল করা
if sys.platform == "win32":
    os.system('color')

# ১. থ্রেড লিমিট সেটিংস
def get_max_threads():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    thread_file = os.path.join(current_dir, 'thread_count.txt')
    if not os.path.exists(thread_file):
        with open(thread_file, 'w') as f: f.write("2")
        return 2
    with open(thread_file, 'r') as f:
        try: return int(f.read().strip())
        except: return 2

MAX_THREADS = get_max_threads()
thread_limiter = threading.Semaphore(MAX_THREADS)

# ২. স্ট্যাটাস ট্র্যাকার
manager_stats = {
    'all_accounts': 0,
    'login_fail': 0,
    'running': 0,
    'success_posts': 0,
    'errors': 0,
    'remaining': 0
}
success_logs = []
log_lock = threading.Lock()

def save_to_excel(data):
    """সফল পোস্টের সাথে সাথেই এক্সেল আপডেট করবে"""
    report_path = os.path.join(os.path.dirname(__file__), 'success_report.xlsx')
    with log_lock:
        success_logs.append(data)
        pd.DataFrame(success_logs).to_excel(report_path, index=False)

def update_terminal_title():
    """টাইটেল বারে লাইভ স্ট্যাটাস দেখাবে"""
    status_text = (
        f"[Post Mode] Success: {manager_stats['success_posts']} | "
        f"Total: {manager_stats['all_accounts']} | "
        f"Remaining: {manager_stats['remaining']} | "
        f"Running: {manager_stats['running']}"
    )
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetConsoleTitleW(status_text)

def print_banner(num_threads, acc_count):
    """আপনার রিকোয়েস্ট অনুযায়ী বড় ব্যানার"""
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"""\033[96m
╔══════════════════════════════════════════════════════════════════════════╗
║                                                                          ║
║   \033[97m████████╗██╗   ██╗███╗   ███╗██████╗ ██╗     ██████╗ \033[96m                  ║
║   \033[97m╚══██╔══╝██║   ██║████╗ ████║██╔══██╗██║     ██╔══██╗\033[96m                  ║
║   \033[97m   ██║   ██║   ██║██╔████╔██║██████╔╝██║     ██████╔╝\033[96m                  ║
║   \033[97m   ██║   ██║   ██║██║╚██╔╝██║██╔══██╗██║     ██╔══██╗\033[96m                  ║
║   \033[97m   ██║   ╚██████╔╝██║ ╚═╝ ██║██████╔╝███████╗██║  ██║\033[96m                  ║
║   \033[97m   ╚═╝    ╚═════╝ ╚═╝     ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝\033[96m                  ║
║                                                                          ║
╠══════════════════════════════════════════════════════════════════════════╣
║  \033[93m> Version: 10.0 (Final) \033[96m║ \033[92m> Threads: {num_threads:<3} \033[96m║ \033[92m> Accounts: {acc_count:<3} \033[96m            ║
╚══════════════════════════════════════════════════════════════════════════╝\033[0m""")

def handle_post_confirmation(page, email):
    """পপ-আপ ক্লিয়ারেন্স"""
    try:
        selector = 'button:has-text("Post"):not([aria-label])'
        post_confirm_btn = page.wait_for_selector(selector, state="visible", timeout=4000)
        if post_confirm_btn:
            print(f"\033[94m   [!] [{email}] Handling Tag Popup...\033[0m")
            post_confirm_btn.click(force=True)
            time.sleep(2)
    except:
        pass

def run_account_thread(email, password, image_path, post_link):
    with thread_limiter:
        with log_lock: 
            manager_stats['running'] += 1
            update_terminal_title()
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False) 
            context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            page = context.new_page()

            try:
                # লগইন ডিটেইলস প্রিন্ট
                print(f"\033[93m[~] [{email}] Opening Login Page...\033[0m")
                page.goto('https://www.tumblr.com/login', wait_until='domcontentloaded', timeout=90000)
                
                print(f"\033[90m    - Entering Credentials...\033[0m")
                page.fill('input[name="email"]', email)
                page.keyboard.press("Enter")
                time.sleep(3)
                page.fill('input[name="password"]', password)
                page.keyboard.press("Enter")
                
                print(f"\033[93m[~] [{email}] Waiting for Dashboard...\033[0m")
                time.sleep(10) 

                if page.is_visible('button#community_button'):
                    print(f"\033[92m[+] [{email}] Login Success!\033[0m")
                    page.click('button#community_button')
                    time.sleep(5) 
                else:
                    with log_lock: manager_stats['login_fail'] += 1
                    print(f"\033[91m[-] [{email}] Login Failed or Skip.\033[0m")
                    return

                # কমিউনিটি স্ক্যানিং
                print(f"\033[93m[~] [{email}] Scanning All Communities...\033[0m")
                page.mouse.wheel(0, 800) # স্ক্রল করে সব লিঙ্ক ধরবে
                time.sleep(3)
                community_links = page.eval_on_selector_all('a[href*="/communities/"]', "elements => elements.map(el => el.href)")
                unique_communities = [link for link in list(set(community_links)) if "/communities/" in link and not any(x in link for x in ["/explore", "/posts", "/all"])]
                print(f"\033[96m[*] [{email}] Found {len(unique_communities)} Communities.\033[0m")

                for url in unique_communities:
                    comm_name = url.split('/')[-1]
                    try:
                        print(f"\033[35m[>] Target: {comm_name}...\033[0m")
                        # টাইমআউট ফিক্সের জন্য domcontentloaded ব্যবহার
                        page.goto(url, wait_until='domcontentloaded', timeout=90000)
                        time.sleep(5)
                        
                        # ফটো পোস্ট স্টেপ
                        photo_icon = page.locator('button[aria-label="Photo"]').first
                        if photo_icon.is_visible(timeout=10000):
                            print(f"\033[90m    - Step 1: Photo Posting...\033[0m")
                            photo_icon.click()
                            time.sleep(2)
                            if image_path and os.path.exists(image_path):
                                page.set_input_files('input[type="file"]', image_path)
                                post_btn = page.wait_for_selector('button:has-text("Post now"):not([disabled])', timeout=30000)
                                post_btn.click()
                                handle_post_confirmation(page, email)
                                print(f"\033[32m    [✓] Photo Success!\033[0m")

                        # লিঙ্ক পোস্ট স্টেপ
                        time.sleep(4)
                        link_icon = page.locator('button[aria-label="Link"]').first
                        if link_icon.is_visible(timeout=5000):
                            print(f"\033[90m    - Step 2: Link Posting...\033[0m")
                            link_icon.click()
                            time.sleep(2)
                            link_box = page.locator('div:has-text("Type or paste link"), [role="textbox"]').first
                            link_box.click()
                            page.keyboard.type(post_link)
                            page.keyboard.press("Enter")
                            time.sleep(5)
                            
                            post_btn_link = page.wait_for_selector('button:has-text("Post now"):not([disabled])', timeout=20000)
                            post_btn_link.click()
                            handle_post_confirmation(page, email)
                            
                            # এক্সেল অটো-সেভ
                            save_to_excel({'Email': email, 'Community': url, 'Status': 'Success', 'Time': datetime.now().strftime("%H:%M")})
                            
                            with log_lock:
                                manager_stats['success_posts'] += 1
                                update_terminal_title()
                            print(f"\033[92m    [✓] Link Success & Excel Saved!\033[0m")

                    except Exception:
                        print(f"\033[91m    [!] Error in {comm_name}. Skipping to next...\033[0m")
                        continue
            finally:
                with log_lock: 
                    manager_stats['running'] -= 1
                    manager_stats['remaining'] -= 1
                    update_terminal_title()
                browser.close()

def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    acc_file = os.path.join(current_dir, 'account.txt')
    posts_file = os.path.join(current_dir, 'posts.xlsx')

    if not os.path.exists(acc_file) or not os.path.exists(posts_file):
        print("Required files missing!")
        return

    with open(acc_file, 'r') as f:
        accounts = [line.strip().split(':') for line in f if ':' in line]

    manager_stats['all_accounts'] = len(accounts)
    manager_stats['remaining'] = len(accounts)

    df_posts = pd.read_excel(posts_file)
    row = df_posts.iloc[0] 
    img_path = row['image']
    p_link = str(row['link'])

    print_banner(MAX_THREADS, len(accounts))
    update_terminal_title()

    threads = []
    for email, password in accounts:
        t = threading.Thread(target=run_account_thread, args=(email, password, img_path, p_link))
        t.start()
        threads.append(t)
        time.sleep(5)

    for t in threads: t.join()
    print(f"\n\033[96m{'='*60}\n  DONE! Check 'success_report.xlsx'\n{'='*60}\033[0m")

if __name__ == "__main__":
    main()
