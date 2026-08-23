import time
import pandas as pd
import os
import threading
import random
from playwright.sync_api import sync_playwright
from datetime import datetime

# ১. কালার এবং স্টাইলের জন্য লাইব্রেরি
try:
    from colorama import init, Fore, Style, Back
    init(autoreset=True)
except ImportError:
    os.system('pip install colorama')
    from colorama import init, Fore, Style, Back
    init(autoreset=True)

# ২. থ্রেড এবং রিপোর্ট সেটিংস
def get_max_threads():
    try:
        with open('thread_count.txt', 'r') as f: return int(f.read().strip())
    except: return 2

MAX_THREADS = get_max_threads()
thread_limiter = threading.Semaphore(MAX_THREADS)
success_logs = []
log_lock = threading.Lock()

def save_success_to_excel():
    report_path = os.path.join(os.path.dirname(__file__), 'success_report.xlsx')
    with log_lock:
        if success_logs:
            pd.DataFrame(success_logs).to_excel(report_path, index=False)

# ৩. স্টাইলিশ কনফার্মেশন লজিক
def handle_post_confirmation(page, email):
    try:
        post_btn = page.locator('button:has-text("Post now"), button[aria-label="Post now"], button:has-text("Post")').last
        if post_btn.is_enabled():
            post_btn.click()
            time.sleep(3)
        
        # 'Post without tags?' পপআপ চেক
        confirm_dialog_btn = page.locator('button:has-text("Post")').filter(has_not_text="now").last
        if confirm_dialog_btn.is_visible(timeout=3000):
            confirm_dialog_btn.click()
            time.sleep(3)
            return True
    except: pass
    return False

# ৪. Mature Content বাটন ক্লিক
def check_for_mature_content_warning(page, email):
    try:
        view_btn = page.locator('button:has-text("View community"), [role="button"]:has-text("View community")').first
        if view_btn.is_visible(timeout=4000):
            print(f"{Fore.YELLOW}  >> [{email}] Mature warning bypassed!")
            view_btn.click()
            time.sleep(4)
    except: pass

# ৫. মূল পোস্টিং লজিক (Stylish Status Updates)
def auto_post_to_communities(page, email, image_path, post_link):
    try:
        print(f"\n{Fore.CYAN}[{email}] {Fore.WHITE}Searching for joined communities...")
        page.goto('https://www.tumblr.com/communities', wait_until='networkidle')
        time.sleep(8)
        
        community_links = page.eval_on_selector_all('a[href*="/communities/"]', "elements => elements.map(el => el.href)")
        unique_communities = [l.rstrip('/') for l in list(set(community_links)) if "/communities/" in l and not any(x in l for x in ["/explore", "/posts", "/all", "/tagged"])]

        total_found = len(unique_communities)
        success_count = 0
        
        # কয়টি কমিউনিটি পাওয়া গেছে তা স্টাইলিশ ভাবে দেখানো
        print(f"{Back.BLUE}{Fore.WHITE} FOUND: {total_found} COMMUNITIES {Style.RESET_ALL}\n")

        for index, url in enumerate(unique_communities, 1):
            try:
                print(f"{Fore.MAGENTA}--- Working on Community {index}/{total_found} ---")
                
                photo_done = False
                link_done = False

                # STEP 1: PHOTO POST
                photo_url = f"{url}/new/photo"
                page.goto(photo_url, wait_until='domcontentloaded')
                time.sleep(4)
                check_for_mature_content_warning(page, email)

                if image_path and os.path.exists(image_path):
                    file_input = page.locator('input[type="file"]')
                    if file_input.count() > 0:
                        file_input.set_input_files(os.path.abspath(image_path))
                        time.sleep(12) 
                        handle_post_confirmation(page, email)
                        print(f"{Fore.GREEN}  [✓] PHOTO SUCCESSFUL")
                        photo_done = True

                # STEP 2: LINK POST
                link_url = f"{url}/new/link"
                page.goto(link_url, wait_until='domcontentloaded')
                time.sleep(4)
                check_for_mature_content_warning(page, email)

                if post_link and post_link != "nan":
                    link_input = page.locator('input[placeholder*="link"], input[aria-label*="link"], .editor-link-input').first
                    if link_input.is_visible(timeout=5000):
                        link_input.fill(post_link)
                        time.sleep(2)
                        page.keyboard.press("Enter")
                        time.sleep(6)
                        handle_post_confirmation(page, email)
                        print(f"{Fore.GREEN}  [✓] LINK SUCCESSFUL")
                        link_done = True

                if photo_done or link_done:
                    success_count += 1
                    # বর্তমান সাকসেস রিপোর্ট দেখানো
                    print(f"{Fore.BLACK}{Back.GREEN} STATUS: {success_count}/{total_found} SUCCESSFUL POSTS {Style.RESET_ALL}")
                    
                    with log_lock:
                        success_logs.append({'Email': email, 'Community': url, 'Status': 'Success', 'Time': datetime.now().strftime("%H:%M")})
                    save_success_to_excel()

                time.sleep(random.randint(10, 15))

            except Exception as e:
                print(f"{Fore.RED}  [!] Skip {url}: {e}")
                continue
        
        # ফাইনাল রেজাল্ট
        print(f"\n{Fore.YELLOW}╔══════════════════════════════════════╗")
        print(f"{Fore.YELLOW}║ {Fore.GREEN}FINAL REPORT FOR: {email}")
        print(f"{Fore.YELLOW}║ {Fore.WHITE}Total Processed: {total_found}")
        print(f"{Fore.YELLOW}║ {Fore.CYAN}Total Successful: {success_count}")
        print(f"{Fore.YELLOW}╚══════════════════════════════════════╝\n")

    except Exception as e:
        print(f"{Fore.RED}[{email}] Global Error: {e}")

# ৬. থ্রেড রানার
def run_bot(email, password, tag, image_path, post_link, mode):
    with thread_limiter:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
            pixel_7 = p.devices['Pixel 7']
            context = browser.new_context(**pixel_7, locale='en-US', timezone_id='America/New_York')
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                print(f"{Fore.WHITE}[{email}] Login Processing...")
                page.goto('https://www.tumblr.com/login')
                page.fill('input[name="email"]', email); page.keyboard.press("Enter"); time.sleep(3)
                page.fill('input[name="password"]', password); page.keyboard.press("Enter")
                page.wait_for_url("**/dashboard**", timeout=45000)
                print(f"{Fore.GREEN}[{email}] LOGIN COMPLETE!")

                if mode == "1":
                    page.goto(f"https://www.tumblr.com/tagged/{tag}?sort=community", wait_until='networkidle')
                    time.sleep(10)
                    links = page.locator('a[href*="/communities/"]').all()
                    unique_links = list(set([l.get_attribute('href').split('?')[0].rstrip('/') for l in links if l.get_attribute('href')]))
                    for i in range(min(len(unique_links), 11)):
                        try:
                            page.goto(f"{unique_links[i]}/join"); time.sleep(5)
                            print(f"{Fore.GREEN}[{email}] Joined: {unique_links[i]}")
                        except: pass
                elif mode == "2":
                    auto_post_to_communities(page, email, image_path, post_link)
            except Exception as e:
                print(f"{Fore.RED}[{email}] Error: {e}")
            finally: browser.close()

# ৭. স্টাইলিশ ব্যানার
def display_banner(num_threads, acc_count):
    os.system('cls' if os.name == 'nt' else 'clear')
    c, w, y, g = Fore.CYAN, Fore.WHITE, Fore.YELLOW, Fore.GREEN
    print(f"{c}╔══════════════════════════════════════════════════════════════════════════╗")
    print(f"{c}║   {w}████████╗██╗   ██╗███╗   ███╗██████╗ ██╗     ██████╗ {c}                  ║")
    print(f"{c}║   {w}╚══██╔══╝██║   ██║████╗ ████║██╔══██╗██║     ██╔══██╗{c}                  ║")
    print(f"{c}║   {w}   ██║   ██║   ██║██╔████╔██║██████╔╝██║     ██████╔╝{c}                  ║")
    print(f"{c}║   {w}   ██║   ██║   ██║██║╚██╔╝██║██╔══██╗██║     ██╔══██╗{c}                  ║")
    print(f"{c}║   {w}   ██║   ╚██████╔╝██║ ╚═╝ ██║██████╔╝███████╗██║  ██║{c}                  ║")
    print(f"{c}║   {w}   ╚═╝    ╚═════╝ ╚═╝     ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝{c}                  ║")
    print(f"{c}╠══════════════════════════════════════════════════════════════════════════╣")
    print(f"{c}║  {y}> Version: 23.0 (Smart Report)  {c}║ {g}> Threads: {str(num_threads):<3} {c}║ {g}> Accounts: {str(acc_count):<3} {c}      ║")
    print(f"{c}╚══════════════════════════════════════════════════════════════════════════╝")

def main():
    while True:
        acc_file = 'account.txt'; acc_count = 0
        if os.path.exists(acc_file):
            with open(acc_file, 'r', encoding='utf-8') as f:
                lines = [l.strip() for l in f if ':' in l]; acc_count = len(lines)
        display_banner(MAX_THREADS, acc_count)
        print(f"\n  {Fore.WHITE}[1] Join Communities (Android Mode)")
        print(f"  {Fore.WHITE}[2] Start Step-by-Step Posting (With Live Report)")
        print(f"  {Fore.RED}[X] Exit")
        mode = input(f"\n  {Fore.YELLOW}Select Mode: ").strip()
        if mode.lower() == 'x': break
        if os.path.exists('account.txt') and os.path.exists('posts.xlsx'):
            with open('account.txt', 'r', encoding='utf-8') as f:
                accounts = [line.strip().split(':') for line in f if ':' in line]
            df_p = pd.read_excel('posts.xlsx')
            img = os.path.abspath(df_p.iloc[0]['image'])
            lnk = str(df_p.iloc[0]['link'])
            threads = []
            for acc in accounts:
                email, password = acc[0], acc[1]
                tag = acc[2] if len(acc) > 2 else "Beauty"
                t = threading.Thread(target=run_bot, args=(email, password, tag, img, lnk, mode))
                t.start(); time.sleep(5); threads.append(t)
            for t in threads: t.join()
        if input(f"\n{Fore.CYAN}  Press 0 for Menu: ") != '0': break

if __name__ == "__main__":
    main()
