import time
import pandas as pd
import os
import threading
from playwright.sync_api import sync_playwright
from datetime import datetime

# ১. থ্রেড লিমিট সেটআপ
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
success_logs = []
log_lock = threading.Lock()

def save_success_to_excel():
    report_path = os.path.join(os.path.dirname(__file__), 'success_report.xlsx')
    with log_lock:
        if success_logs:
            pd.DataFrame(success_logs).to_excel(report_path, index=False)
            print(f"--- Report updated: success_report.xlsx ---")

def handle_post_confirmation(page, email):
    try:
        post_confirm_btn = page.locator('button:has-text("Post")').first
        if post_confirm_btn.is_visible(timeout=2000):
            print(f"[{email}] Clicking final Post confirmation...")
            post_confirm_btn.click()
            time.sleep(2)
    except:
        pass

def run_account_thread(email, password, image_path, post_link):
    with thread_limiter:
        with sync_playwright() as p:
            # গিটহাবের জন্য headless=True রাখা হয়েছে
            browser = p.chromium.launch(headless=True) 
            context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            page = context.new_page()

            try:
                print(f"[{email}] Logging in...")
                page.goto('https://www.tumblr.com/login', wait_until='networkidle')
                page.fill('input[name="email"]', email)
                page.keyboard.press("Enter")
                time.sleep(2) 
                page.fill('input[name="password"]', password)
                page.keyboard.press("Enter")
                time.sleep(5) 

                if page.is_visible('button#community_button'):
                    page.click('button#community_button')
                    time.sleep(5) 

                community_links = page.eval_on_selector_all(
                    'a[href*="/communities/"]', 
                    "elements => elements.map(el => el.href)"
                )
                
                unique_communities = [link for link in list(set(community_links)) if "/communities/" in link and not any(x in link for x in ["/explore", "/posts", "/all"])]
                print(f"[{email}] Found {len(unique_communities)} communities.")

                for url in unique_communities:
                    try:
                        print(f"[{email}] Navigating to: {url}")
                        page.goto(url, wait_until='networkidle')
                        time.sleep(3)

                        view_btn = page.query_selector('button:has-text("View community")')
                        if view_btn:
                            view_btn.click()
                            time.sleep(3)

                        # --- ফটো পোস্ট ---
                        print(f"[{email}] Step 1: Uploading Photo...")
                        page.click('button[aria-label="Photo"]') 
                        time.sleep(3)
                        
                        if image_path and os.path.exists(image_path):
                            page.set_input_files('input[type="file"]', image_path)
                            time.sleep(8) 
                            page.wait_for_selector('button:has-text("Post now"):not([disabled])', timeout=20000)
                            page.click('button:has-text("Post now")')
                            time.sleep(3)
                            handle_post_confirmation(page, email)
                            print(f"[{email}] Photo posted.")

                        # --- লিঙ্ক পোস্ট ---
                        print(f"[{email}] Step 2: Posting Link...")
                        page.click('button[aria-label="Link"]')
                        time.sleep(3) 
                        
                        link_box = page.locator('div:has-text("Type or paste link"), [role="textbox"]').first
                        if link_box:
                            link_box.click()
                            time.sleep(2)
                            page.keyboard.type(post_link)
                            time.sleep(2)
                            page.keyboard.press("Enter")
                            time.sleep(3)
                        
                        post_btn = page.locator('button:has-text("Post now"):not([disabled])').first
                        if post_btn.is_visible(timeout=10000):
                            post_btn.click()
                            time.sleep(5)
                            handle_post_confirmation(page, email)
                            print(f"[{email}] Link posted successfully.")

                        with log_lock:
                            success_logs.append({'Email': email, 'Community': url, 'Status': 'Success', 'Time': datetime.now().strftime("%H:%M")})
                        save_success_to_excel()

                    except Exception as e:
                        print(f"Error in {url}: {e}")
                        continue

            except Exception as e:
                print(f"Critical error for {email}: {e}")
            finally:
                browser.close()

def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    acc_file = os.path.join(current_dir, 'account.txt')
    posts_file = os.path.join(current_dir, 'posts.xlsx')

    if not os.path.exists(acc_file) or not os.path.exists(posts_file):
        print(f"Required files missing! Checked at: {current_dir}")
        return

    with open(acc_file, 'r') as f:
        accounts = [line.strip().split(':') for line in f if ':' in line]

    df_posts = pd.read_excel(posts_file)
    row = df_posts.iloc[0] 
    
    # ছবির নাম এবং পাথের সমন্বয়
    img_name = row['image']
    img_path = os.path.join(current_dir, img_name)
    p_link = str(row['link'])

    threads = []
    for email, password in accounts:
        t = threading.Thread(target=run_account_thread, args=(email, password, img_path, p_link))
        t.start()
        threads.append(t)
        time.sleep(3)

    for t in threads: t.join()

if __name__ == "__main__":
    main()